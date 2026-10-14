from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys

from celery.schedules import crontab
import httpx
import pytest
from sqlalchemy import select


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.celery_app import celery_app
from app.config import Settings
from app.models import MarketBar
from app.services.price_feed import build_price_message
from app.services.market_ingestion import RetryPolicy, detect_gaps, parse_provider_bars, sync_bars, sync_bars_with_details
from app.services.market_ingestion.service import SUPPORTED_TIMEFRAMES, SyncSummary
from app.tasks.market import _publish_latest_price, task_sync_market_bars


def _provider_payload(*timestamps: object) -> dict[str, object]:
    points = list(timestamps)
    return {
        "chart": {
            "result": [
                {
                    "timestamp": points,
                    "indicators": {
                        "quote": [
                            {
                                "open": [2300.1 + index for index in range(len(points))],
                                "high": [2301.1 + index for index in range(len(points))],
                                "low": [2299.1 + index for index in range(len(points))],
                                "close": [2300.6 + index for index in range(len(points))],
                                "volume": [100 + index for index in range(len(points))],
                            }
                        ]
                    },
                }
            ]
        }
    }


def test_parse_provider_bars_normalizes_offset_timestamps_to_utc() -> None:
    payload = _provider_payload("2026-04-01T09:00:00-04:00")

    bars = parse_provider_bars(
        payload,
        symbol="XAUUSD",
        timeframe="1h",
        data_source="mock_feed",
    )

    assert len(bars) == 1
    assert bars[0].bar_time == datetime(2026, 4, 1, 13, 0, tzinfo=UTC)
    assert bars[0].open == Decimal("2300.1")
    assert bars[0].volume == Decimal("100")


def test_fetch_provider_payload_sends_user_agent_header(monkeypatch) -> None:
    from app.services.market_ingestion import service as market_service

    captured: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"chart": {"result": []}}

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured["headers"] = kwargs.get("headers")

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

        def get(self, url: str, params: dict | None = None) -> _FakeResponse:
            captured["url"] = url
            return _FakeResponse()

    monkeypatch.setattr(market_service.httpx, "Client", _FakeClient)

    market_service.fetch_provider_payload(
        "GC=F",
        "1h",
        datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
        datetime(2026, 4, 1, 5, 0, tzinfo=UTC),
        10.0,
    )

    headers = captured["headers"]
    assert headers is not None and "User-Agent" in headers
    assert headers["User-Agent"] == market_service.MARKET_DATA_USER_AGENT
    assert "GC=F" in str(captured["url"])


def test_sync_bars_inserts_rows_and_skips_duplicates(db_session) -> None:
    payload = _provider_payload(
        datetime(2026, 4, 1, 10, 0, tzinfo=UTC).timestamp(),
        datetime(2026, 4, 1, 11, 0, tzinfo=UTC).timestamp(),
        datetime(2026, 4, 1, 12, 0, tzinfo=UTC).timestamp(),
    )
    settings = Settings(market_data_source="mock_feed")

    def fetcher(provider_symbol: str, timeframe: str, start: datetime, end: datetime, timeout_seconds: float):
        assert provider_symbol == "XAUUSD=X"
        assert timeframe == "1h"
        assert timeout_seconds == settings.market_fetch_timeout_seconds
        return payload

    first_inserted = sync_bars(
        db_session,
        symbol="XAUUSD",
        timeframe="1h",
        start=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        end=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        settings=settings,
        provider_fetcher=fetcher,
    )

    second_inserted = sync_bars(
        db_session,
        symbol="XAUUSD",
        timeframe="1h",
        start=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        end=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        settings=settings,
        provider_fetcher=fetcher,
    )

    stored_bars = db_session.execute(select(MarketBar).order_by(MarketBar.bar_time.asc())).scalars().all()

    assert first_inserted == 3
    assert second_inserted == 0
    assert len(stored_bars) == 3
    assert stored_bars[0].symbol == "XAUUSD"
    assert stored_bars[0].timeframe == "1h"
    assert stored_bars[0].data_source == "mock_feed"


def test_detect_gaps_reports_missing_hour_without_inventing_rows(db_session) -> None:
    payload = _provider_payload(
        datetime(2026, 4, 1, 10, 0, tzinfo=UTC).timestamp(),
        datetime(2026, 4, 1, 12, 0, tzinfo=UTC).timestamp(),
    )

    summary = sync_bars_with_details(
        db_session,
        symbol="XAUUSD",
        timeframe="1h",
        start=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        end=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        settings=Settings(market_data_source="mock_feed"),
        provider_fetcher=lambda provider_symbol, timeframe, start, end, timeout_seconds: payload,
    )

    stored_count = db_session.execute(select(MarketBar)).scalars().all()

    assert summary.gap_count == 1
    assert summary.gaps == (datetime(2026, 4, 1, 11, 0, tzinfo=UTC),)
    assert len(stored_count) == 2


def test_subsequent_sync_refills_missing_gap_when_history_window_still_covers_it(db_session) -> None:
    incomplete_payload = _provider_payload(
        datetime(2026, 4, 1, 10, 0, tzinfo=UTC).timestamp(),
        datetime(2026, 4, 1, 12, 0, tzinfo=UTC).timestamp(),
    )
    complete_payload = _provider_payload(
        datetime(2026, 4, 1, 10, 0, tzinfo=UTC).timestamp(),
        datetime(2026, 4, 1, 11, 0, tzinfo=UTC).timestamp(),
        datetime(2026, 4, 1, 12, 0, tzinfo=UTC).timestamp(),
    )
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    end = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    settings = Settings(market_data_source="mock_feed")

    first_summary = sync_bars_with_details(
        db_session,
        symbol="XAUUSD",
        timeframe="1h",
        start=start,
        end=end,
        settings=settings,
        provider_fetcher=lambda provider_symbol, timeframe, start, end, timeout_seconds: incomplete_payload,
    )

    second_summary = sync_bars_with_details(
        db_session,
        symbol="XAUUSD",
        timeframe="1h",
        start=start,
        end=end,
        settings=settings,
        provider_fetcher=lambda provider_symbol, timeframe, start, end, timeout_seconds: complete_payload,
    )

    stored_bars = db_session.execute(select(MarketBar).order_by(MarketBar.bar_time.asc())).scalars().all()

    assert first_summary.gap_count == 1
    assert second_summary.bars_inserted == 1
    assert second_summary.gap_count == 0
    assert [bar.bar_time for bar in stored_bars] == [
        datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        datetime(2026, 4, 1, 11, 0, tzinfo=UTC),
        datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
    ]


def test_detect_gaps_handles_empty_or_single_bar_sequences() -> None:
    assert detect_gaps([], "1h") == ()
    assert detect_gaps([datetime(2026, 4, 1, 10, 0, tzinfo=UTC)], "1h") == ()


def test_supported_timeframes_include_phase2_runtime_intervals() -> None:
    assert SUPPORTED_TIMEFRAMES == {
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
    }


def test_detect_gaps_uses_phase2_timeframe_steps() -> None:
    assert detect_gaps(
        [
            datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 4, 1, 10, 45, tzinfo=UTC),
        ],
        "15m",
    ) == (
        datetime(2026, 4, 1, 10, 15, tzinfo=UTC),
        datetime(2026, 4, 1, 10, 30, tzinfo=UTC),
    )
    assert detect_gaps(
        [
            datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
            datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
        ],
        "4h",
    ) == (datetime(2026, 4, 1, 4, 0, tzinfo=UTC),)
    assert detect_gaps(
        [
            datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
            datetime(2026, 4, 3, 0, 0, tzinfo=UTC),
        ],
        "1d",
    ) == (datetime(2026, 4, 2, 0, 0, tzinfo=UTC),)


def test_sync_bars_public_interface_returns_written_row_count(db_session) -> None:
    payload = _provider_payload(datetime(2026, 4, 1, 10, 0, tzinfo=UTC).timestamp())

    inserted = sync_bars(
        db_session,
        symbol="XAUUSD",
        timeframe="1h",
        start=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        end=datetime(2026, 4, 1, 10, 0, 1, tzinfo=UTC),
        settings=Settings(market_data_source="mock_feed"),
        provider_fetcher=lambda provider_symbol, timeframe, start, end, timeout_seconds: payload,
    )

    assert inserted == 1


def test_sync_bars_retries_with_exponential_backoff_for_retryable_failures(db_session) -> None:
    payload = _provider_payload(datetime(2026, 4, 1, 10, 0, tzinfo=UTC).timestamp())
    attempts = {"count": 0}
    sleep_calls: list[float] = []

    def fetcher(provider_symbol: str, timeframe: str, start: datetime, end: datetime, timeout_seconds: float):
        attempts["count"] += 1
        if attempts["count"] < 3:
            request = httpx.Request("GET", "https://example.com/chart")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return payload

    summary = sync_bars_with_details(
        db_session,
        symbol="XAUUSD",
        timeframe="1h",
        start=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        end=datetime(2026, 4, 1, 10, 0, 1, tzinfo=UTC),
        settings=Settings(market_data_source="mock_feed"),
        provider_fetcher=fetcher,
        retry_policy=RetryPolicy(max_attempts=4, initial_delay_seconds=0.5, backoff_multiplier=2.0),
        sleeper=sleep_calls.append,
    )

    assert attempts["count"] == 3
    assert sleep_calls == [0.5, 1.0]
    assert summary.bars_inserted == 1


def test_market_provider_failover_uses_second_configured_source() -> None:
    from app.services.market_ingestion.service import fetch_provider_payload_with_failover

    settings = Settings(
        market_data_source="primary_feed",
        market_data_sources_json=json.dumps(
            [
                {"name": "primary_feed", "symbol_map": {"XAUUSD": "XAUUSD_PRIMARY"}},
                {"name": "backup_feed", "symbol_map": {"XAUUSD": "XAUUSD_BACKUP"}},
            ]
        ),
    )
    attempts: list[tuple[str, str]] = []
    payload = _provider_payload(datetime(2026, 4, 1, 10, 0, tzinfo=UTC).timestamp())

    def fetcher(provider_symbol: str, timeframe: str, start: datetime, end: datetime, timeout_seconds: float):
        attempts.append((provider_symbol, timeframe))
        if provider_symbol == "XAUUSD_PRIMARY":
            raise httpx.ReadTimeout("primary timed out")
        return payload

    result = fetch_provider_payload_with_failover(
        "XAUUSD",
        "1h",
        datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        datetime(2026, 4, 1, 11, 0, tzinfo=UTC),
        settings=settings,
        provider_fetcher=fetcher,
        retry_policy=RetryPolicy(max_attempts=1),
        sleeper=lambda delay: None,
    )

    assert result.provider_name == "backup_feed"
    assert result.payload == payload
    assert attempts == [("XAUUSD_PRIMARY", "1h"), ("XAUUSD_BACKUP", "1h")]


def test_sync_bars_does_not_retry_non_retryable_failures(db_session) -> None:
    sleep_calls: list[float] = []
    attempts = {"count": 0}

    def fetcher(provider_symbol: str, timeframe: str, start: datetime, end: datetime, timeout_seconds: float):
        attempts["count"] += 1
        request = httpx.Request("GET", "https://example.com/chart")
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        sync_bars(
            db_session,
            symbol="XAUUSD",
            timeframe="1h",
            start=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
            end=datetime(2026, 4, 1, 10, 0, 1, tzinfo=UTC),
            settings=Settings(market_data_source="mock_feed"),
            provider_fetcher=fetcher,
            retry_policy=RetryPolicy(max_attempts=4, initial_delay_seconds=0.5, backoff_multiplier=2.0),
            sleeper=sleep_calls.append,
        )

    assert attempts["count"] == 1
    assert sleep_calls == []


def test_task_sync_market_bars_runs_without_real_network(monkeypatch) -> None:
    class FakeSession:
        def close(self) -> None:
            return None

    class FakeSessionFactory:
        def configure(self, **kwargs) -> None:
            return None

        def __call__(self) -> FakeSession:
            return FakeSession()

    class FakeEngine:
        def dispose(self) -> None:
            return None

    monkeypatch.setattr("app.tasks.market.get_engine", lambda: FakeEngine())
    monkeypatch.setattr("app.tasks.market.SessionLocal", FakeSessionFactory())
    monkeypatch.setattr("app.tasks.market.get_settings", lambda: Settings(market_data_source="mock_feed"))
    monkeypatch.setattr(
        "app.tasks.market.sync_bars_with_details",
        lambda session, symbol, timeframe, start, end, settings: SyncSummary(
            bars_seen=2,
            bars_inserted=2,
            bars_skipped=0,
            gap_count=0,
            gaps=(),
        ),
    )
    monkeypatch.setattr("app.tasks.market._publish_latest_price", lambda session, symbol, timeframe, as_of: True)

    result = task_sync_market_bars(
        symbol="XAUUSD",
        timeframe="1h",
        start_iso="2026-04-01T10:00:00+00:00",
        end_iso="2026-04-01T11:00:00+00:00",
    )

    assert result["bars_inserted"] == 2
    assert result["bars_skipped"] == 0
    assert result["gap_count"] == 0
    assert result["price_published"] is True


def test_task_publish_latest_price_uses_latest_persisted_bar(db_session) -> None:
    older = MarketBar(
        symbol="XAUUSD",
        timeframe="15m",
        bar_time=datetime(2026, 4, 30, 1, 0, tzinfo=UTC),
        open=Decimal("2320.00"),
        high=Decimal("2322.00"),
        low=Decimal("2319.00"),
        close=Decimal("2321.00"),
        volume=Decimal("100"),
        data_source="mock_feed",
    )
    latest = MarketBar(
        symbol="XAUUSD",
        timeframe="15m",
        bar_time=datetime(2026, 4, 30, 1, 15, tzinfo=UTC),
        open=Decimal("2321.00"),
        high=Decimal("2323.00"),
        low=Decimal("2320.00"),
        close=Decimal("2322.12345678"),
        volume=Decimal("101"),
        data_source="mock_feed",
    )
    db_session.add_all([older, latest])
    db_session.commit()
    published: list[dict[str, object]] = []

    class FakePublisher:
        def publish(self, message: dict[str, object]) -> int:
            published.append(message)
            return 1

    did_publish = _publish_latest_price(
        db_session,
        symbol="XAUUSD",
        timeframe="15m",
        as_of=datetime(2026, 4, 30, 1, 20, tzinfo=UTC),
        publisher=FakePublisher(),
    )

    assert did_publish is True
    assert published == [
        build_price_message(
            symbol="XAUUSD",
            timeframe="15m",
            price=Decimal("2322.12345678"),
            as_of=datetime(2026, 4, 30, 1, 15, tzinfo=UTC),
        )
    ]


def test_task_sync_market_bars_defaults_to_configured_refill_window(monkeypatch) -> None:
    class FakeSession:
        def close(self) -> None:
            return None

    class FakeSessionFactory:
        def configure(self, **kwargs) -> None:
            return None

        def __call__(self) -> FakeSession:
            return FakeSession()

    class FakeEngine:
        def dispose(self) -> None:
            return None

    captured: dict[str, object] = {}
    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 4, 8, 0, 0, tzinfo=UTC)

    monkeypatch.setattr("app.tasks.market.get_engine", lambda: FakeEngine())
    monkeypatch.setattr("app.tasks.market.SessionLocal", FakeSessionFactory())
    monkeypatch.setattr("app.tasks.market.get_settings", lambda: Settings(market_sync_lookback_hours=168))
    monkeypatch.setattr("app.tasks.market._default_window", lambda lookback_hours: (start, end))
    monkeypatch.setattr("app.tasks.market._publish_latest_price", lambda session, symbol, timeframe, as_of: False)

    def fake_sync(session, symbol, timeframe, start, end, settings):
        captured["symbol"] = symbol
        captured["timeframe"] = timeframe
        captured["start"] = start
        captured["end"] = end
        captured["lookback"] = settings.market_sync_lookback_hours
        return SyncSummary(bars_seen=3, bars_inserted=1, bars_skipped=2, gap_count=0, gaps=())

    monkeypatch.setattr("app.tasks.market.sync_bars_with_details", fake_sync)

    result = task_sync_market_bars(symbol="XAUUSD", timeframe="1h")

    assert captured == {
        "symbol": "XAUUSD",
        "timeframe": "1h",
        "start": start,
        "end": end,
        "lookback": 168,
    }
    assert result["start"] == start.isoformat()
    assert result["end"] == end.isoformat()


def test_celery_beat_schedule_wires_market_task_hourly_in_utc() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["sync-market-bars-hourly"]["task"] == "app.tasks.market.task_sync_market_bars"
    assert schedule["sync-market-bars-hourly"]["schedule"] == crontab(minute=0)
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"


def test_celery_beat_schedule_wires_phase2_market_timeframes_in_utc() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["sync-market-bars-15m"]["task"] == "app.tasks.market.task_sync_market_bars"
    assert schedule["sync-market-bars-15m"]["schedule"] == crontab(minute="*/15")
    assert schedule["sync-market-bars-15m"]["kwargs"] == {"timeframe": "15m"}

    assert schedule["sync-market-bars-hourly"]["task"] == "app.tasks.market.task_sync_market_bars"
    assert schedule["sync-market-bars-hourly"]["schedule"] == crontab(minute=0)
    assert schedule["sync-market-bars-hourly"]["kwargs"] == {"timeframe": "1h"}

    assert schedule["sync-market-bars-4h"]["task"] == "app.tasks.market.task_sync_market_bars"
    assert schedule["sync-market-bars-4h"]["schedule"] == crontab(minute=0, hour="*/4")
    assert schedule["sync-market-bars-4h"]["kwargs"] == {"timeframe": "4h"}

    assert schedule["sync-market-bars-daily"]["task"] == "app.tasks.market.task_sync_market_bars"
    assert schedule["sync-market-bars-daily"]["schedule"] == crontab(minute=0, hour=0)
    assert schedule["sync-market-bars-daily"]["kwargs"] == {"timeframe": "1d"}

    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"
