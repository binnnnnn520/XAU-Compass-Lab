from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sys
import uuid

import httpx


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.auth.dependencies import require_trader, require_viewer
from app.database import get_session
from app.main import app
from app.models import MarketBar, NewsItem, SentimentScore, StrategyRun


def _market_bar(hours: int, open_price: str, close_price: str) -> MarketBar:
    open_decimal = Decimal(open_price)
    close_decimal = Decimal(close_price)
    return MarketBar(
        timeframe="1h",
        bar_time=datetime(2026, 4, 1, hours, 0, tzinfo=UTC),
        open=open_decimal,
        high=max(open_decimal, close_decimal) + Decimal("1.00000000"),
        low=min(open_decimal, close_decimal) - Decimal("1.00000000"),
        close=close_decimal,
        volume=Decimal("10.00000000"),
    )


def _sentiment_fixture(*, published_at: datetime, title_hash: str, score: str) -> tuple[NewsItem, SentimentScore]:
    item = NewsItem(
        title=f"API Fixture {title_hash[:8]}",
        content="Fixture content",
        published_at=published_at,
        title_hash=title_hash,
        status="analyzed",
    )
    sentiment = SentimentScore(
        news_item=item,
        analyzer_type="rule_based",
        sentiment="positive" if Decimal(score) > 0 else "negative",
        score=Decimal(score),
        confidence=Decimal("0.9000"),
        reasoning="Fixture sentiment",
        created_at=published_at + timedelta(minutes=1),
    )
    return item, sentiment


def _seed_backtest_api_data(db_session) -> StrategyRun:
    strategy = StrategyRun(
        strategy_name="api_backtest_v1",
        version="1.0.0",
        parameters={
            "lookback_hours": 2,
            "momentum_bars": 1,
            "positive_sentiment_threshold": "0.3000",
            "negative_sentiment_threshold": "-0.3000",
            "positive_momentum_threshold": "0.0001",
            "negative_momentum_threshold": "-0.0001",
        },
        is_active=True,
    )
    positive_news, positive_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 1, 30, tzinfo=UTC),
        title_hash="5" * 64,
        score="0.8000",
    )
    negative_news, negative_sentiment = _sentiment_fixture(
        published_at=datetime(2026, 4, 1, 3, 30, tzinfo=UTC),
        title_hash="6" * 64,
        score="-0.9000",
    )
    db_session.add(strategy)
    db_session.add_all(
        [
            positive_news,
            positive_sentiment,
            negative_news,
            negative_sentiment,
            _market_bar(0, "100.00000000", "100.00000000"),
            _market_bar(1, "100.00000000", "101.00000000"),
            _market_bar(2, "102.00000000", "104.00000000"),
            _market_bar(3, "104.00000000", "103.00000000"),
            _market_bar(4, "103.00000000", "99.00000000"),
            _market_bar(5, "99.00000000", "98.00000000"),
        ]
    )
    db_session.commit()
    return strategy


async def _request(
    db_session,
    method: str,
    path: str,
    *,
    params: dict[str, object] | None = None,
    json: dict[str, object] | None = None,
) -> httpx.Response:
    def override_db():
        yield db_session

    def override_trader():
        return None

    def override_viewer():
        return None

    app.dependency_overrides[get_session] = override_db
    app.dependency_overrides[require_trader] = override_trader
    app.dependency_overrides[require_viewer] = override_viewer
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, params=params, json=json)
    finally:
        app.dependency_overrides.clear()


def test_backtest_endpoints_create_get_and_list(db_session) -> None:
    strategy = _seed_backtest_api_data(db_session)

    create_response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/backtest",
            json={
                "strategy_run_id": str(strategy.id),
                "start_date": "2026-04-01",
                "end_date": "2026-04-01",
                "initial_capital": "1000.00",
                "slippage_bps": 0,
                "commission_bps": 0,
            },
        )
    )

    assert create_response.status_code == 200
    create_payload = create_response.json()
    assert create_payload["success"] is True
    assert create_payload["data"]["status"] == "pending"
    assert create_payload["data"]["message"] == "Backtest task queued"
    backtest_id = create_payload["data"]["backtest_id"]

    detail_response = asyncio.run(_request(db_session, "GET", f"/api/v1/backtest/{backtest_id}"))
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["success"] is True
    assert detail_payload["data"]["status"] == "completed"
    assert Decimal(detail_payload["data"]["final_capital"]) == Decimal("1058.82")
    assert len(detail_payload["data"]["equity_curve"]) == 6
    assert isinstance(detail_payload["data"]["equity_curve"][0], list)
    assert detail_payload["data"]["equity_curve"][0] == ["2026-04-01T00:00:00Z", "1000.00"]
    assert len(detail_payload["data"]["trade_log"]) == 2

    list_response = asyncio.run(
        _request(
            db_session,
            "GET",
            "/api/v1/backtest",
            params={"strategy_run_id": str(strategy.id), "status": "completed", "page": 1, "page_size": 10},
        )
    )
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["success"] is True
    assert list_payload["data"]["total"] == 1
    assert list_payload["data"]["items"][0]["id"] == backtest_id


def test_backtest_create_returns_insufficient_data_error_code(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="api_insufficient_v1",
        version="1.0.0",
        parameters={"lookback_hours": 2, "momentum_bars": 1},
        is_active=True,
    )
    db_session.add(strategy)
    db_session.add(_market_bar(0, "100.00000000", "100.00000000"))
    db_session.commit()

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/backtest",
            json={
                "strategy_run_id": str(strategy.id),
                "start_date": "2026-04-01",
                "end_date": "2026-04-01",
                "initial_capital": "1000.00",
                "slippage_bps": 0,
                "commission_bps": 0,
            },
        )
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "BACKTEST_DATA_INSUFFICIENT"


def test_backtest_unknown_id_returns_not_found(db_session) -> None:
    _seed_backtest_api_data(db_session)

    response = asyncio.run(_request(db_session, "GET", f"/api/v1/backtest/{uuid.uuid4()}"))

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "NOT_FOUND"
