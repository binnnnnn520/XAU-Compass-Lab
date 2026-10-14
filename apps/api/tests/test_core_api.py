from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import sys
import uuid

import httpx
import pytest


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.auth.dependencies import require_viewer
from app.database import get_session
from app.main import app
from app.models import EventTag, NewsItem, NewsSource, SentimentScore, Signal, StrategyRun


def _seed_core_api_data(db_session):
    source = NewsSource(
        name="Reuters",
        source_type="rss",
        url="https://example.com/reuters.xml",
    )
    strategy = StrategyRun(
        strategy_name="sentiment_momentum_v1",
        version="1.0.0",
        parameters={"lookback_hours": 24},
        is_active=True,
    )

    positive_news = NewsItem(
        source=source,
        title="Gold rises on dovish Fed expectations",
        summary="Bullion extends gains.",
        content="Markets expect rate cuts and geopolitical tension supports gold.",
        url="https://example.com/news-positive",
        author="Desk",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        title_hash="1" * 64,
        status="analyzed",
    )
    pending_news = NewsItem(
        source=source,
        title="Gold holds steady before payrolls",
        summary="Markets await fresh data.",
        published_at=datetime(2026, 4, 1, 11, 0, tzinfo=UTC),
        title_hash="2" * 64,
        status="pending",
    )
    negative_news = NewsItem(
        source=source,
        title="Dollar strength pressures gold",
        summary="Hawkish tone weighs on metals.",
        content="Treasury yields rise and gold eases.",
        published_at=datetime(2026, 3, 30, 9, 0, tzinfo=UTC),
        title_hash="3" * 64,
        status="analyzed",
    )

    positive_sentiment = SentimentScore(
        news_item=positive_news,
        analyzer_type="rule_based",
        sentiment="positive",
        score=Decimal("0.7000"),
        confidence=Decimal("0.8100"),
        reasoning="Prepared positive fixture.",
        metadata_json={"fixture": "positive"},
        created_at=datetime(2026, 4, 1, 10, 5, tzinfo=UTC),
    )
    negative_sentiment = SentimentScore(
        news_item=negative_news,
        analyzer_type="rule_based",
        sentiment="negative",
        score=Decimal("-0.6000"),
        confidence=Decimal("0.7300"),
        reasoning="Prepared negative fixture.",
        metadata_json={"fixture": "negative"},
        created_at=datetime(2026, 3, 30, 9, 5, tzinfo=UTC),
    )

    positive_event = EventTag(
        news_item=positive_news,
        tag_type="monetary_policy",
        tag_value="fed_rate_cut",
        relevance_score=Decimal("0.9200"),
        metadata_json={"fixture": True},
        created_at=datetime(2026, 4, 1, 10, 6, tzinfo=UTC),
    )
    geopolitical_event = EventTag(
        news_item=positive_news,
        tag_type="geopolitical",
        tag_value="war_escalation",
        relevance_score=Decimal("0.8800"),
        metadata_json={"fixture": True},
        created_at=datetime(2026, 4, 1, 10, 7, tzinfo=UTC),
    )
    negative_event = EventTag(
        news_item=negative_news,
        tag_type="economic_data",
        tag_value="strong_dollar",
        relevance_score=Decimal("0.7900"),
        metadata_json={"fixture": True},
        created_at=datetime(2026, 3, 30, 9, 6, tzinfo=UTC),
    )

    live_signal = Signal(
        strategy_run=strategy,
        symbol="XAUUSD",
        signal_time=datetime(2026, 4, 1, 10, 0, 1, tzinfo=UTC),
        direction="BUY",
        strength=Decimal("0.7800"),
        confidence=Decimal("0.8200"),
        price_at_signal=Decimal("2310.00000000"),
        features_used={"sentiment_mean": "0.7000"},
        reasoning="Positive sentiment with supporting momentum.",
        source_type="live",
        created_at=datetime(2026, 4, 1, 10, 0, 2, tzinfo=UTC),
    )
    backtest_signal = Signal(
        strategy_run=strategy,
        symbol="XAUUSD",
        signal_time=datetime(2026, 3, 30, 9, 0, 1, tzinfo=UTC),
        direction="SELL",
        strength=Decimal("0.4200"),
        confidence=Decimal("0.4000"),
        price_at_signal=Decimal("2288.00000000"),
        features_used={"sentiment_mean": "-0.6000"},
        reasoning="Negative sentiment with weaker price action.",
        source_type="backtest",
        created_at=datetime(2026, 3, 30, 9, 0, 2, tzinfo=UTC),
    )

    db_session.add_all(
        [
            source,
            strategy,
            positive_news,
            pending_news,
            negative_news,
            positive_sentiment,
            negative_sentiment,
            positive_event,
            geopolitical_event,
            negative_event,
            live_signal,
            backtest_signal,
        ]
    )
    db_session.commit()

    return {
        "source_id": source.id,
        "positive_news_id": positive_news.id,
        "strategy_run_id": strategy.id,
    }


async def _request(db_session, path: str, *, params: dict[str, object] | None = None) -> httpx.Response:
    def override_db():
        yield db_session

    def override_viewer():
        return None

    app.dependency_overrides[get_session] = override_db
    app.dependency_overrides[require_viewer] = override_viewer
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, params=params)
    finally:
        app.dependency_overrides.clear()


def test_news_list_supports_unified_envelope_pagination_and_filters(db_session) -> None:
    seed = _seed_core_api_data(db_session)

    response = asyncio.run(
        _request(
            db_session,
            "/api/v1/news",
            params={
                "page": 1,
                "page_size": 1,
                "source_id": str(seed["source_id"]),
                "status": "analyzed",
                "sentiment": "positive",
                "start_date": "2026-04-01T00:00:00Z",
                "end_date": "2026-04-01T23:59:59Z",
            },
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["total"] == 1
    assert payload["data"]["page"] == 1
    assert payload["data"]["page_size"] == 1
    assert len(payload["data"]["items"]) == 1
    item = payload["data"]["items"][0]
    assert item["title"] == "Gold rises on dovish Fed expectations"
    assert item["source_name"] == "Reuters"
    assert item["status"] == "analyzed"
    assert item["sentiment"]["label"] == "positive"
    assert Decimal(item["sentiment"]["score"]) == Decimal("0.7000")
    assert item["event_tags"] == ["fed_rate_cut", "war_escalation"]


def test_news_detail_returns_related_sentiment_and_event_data(db_session) -> None:
    seed = _seed_core_api_data(db_session)

    response = asyncio.run(_request(db_session, f"/api/v1/news/{seed['positive_news_id']}"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["title"] == "Gold rises on dovish Fed expectations"
    assert payload["data"]["source_name"] == "Reuters"
    assert len(payload["data"]["sentiment_scores"]) == 1
    assert payload["data"]["sentiment_scores"][0]["metadata"]["fixture"] == "positive"
    assert len(payload["data"]["event_tags"]) == 2
    assert payload["data"]["event_tags"][0]["tag_value"] in {"fed_rate_cut", "war_escalation"}


def test_sentiment_aggregate_returns_windowed_counts_and_dominant_events(db_session, monkeypatch) -> None:
    _seed_core_api_data(db_session)
    fixed_now = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.core_api.utcnow", lambda: fixed_now)

    response = asyncio.run(
        _request(
            db_session,
            "/api/v1/sentiment/aggregate",
            params={"window": "4h", "symbol": "XAUUSD"},
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["window"] == "4h"
    assert Decimal(payload["data"]["avg_score"]) == Decimal("0.7000")
    assert payload["data"]["positive_count"] == 1
    assert payload["data"]["negative_count"] == 0
    assert payload["data"]["neutral_count"] == 0
    assert payload["data"]["dominant_events"] == ["fed_rate_cut", "war_escalation"]


def test_events_endpoint_supports_filters_and_pagination(db_session) -> None:
    _seed_core_api_data(db_session)

    response = asyncio.run(
        _request(
            db_session,
            "/api/v1/events",
            params={
                "page": 1,
                "page_size": 1,
                "tag_type": "monetary_policy",
                "start_date": "2026-04-01T10:00:00Z",
                "end_date": "2026-04-01T11:00:00Z",
            },
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["total"] == 1
    assert payload["data"]["page"] == 1
    assert payload["data"]["page_size"] == 1
    assert payload["data"]["items"][0]["tag_value"] == "fed_rate_cut"
    assert payload["data"]["items"][0]["news_title"] == "Gold rises on dovish Fed expectations"
    assert Decimal(payload["data"]["items"][0]["relevance_score"]) == Decimal("0.9200")


def test_signals_endpoint_supports_filters_and_pagination(db_session) -> None:
    seed = _seed_core_api_data(db_session)

    response = asyncio.run(
        _request(
            db_session,
            "/api/v1/signals",
            params={
                "page": 1,
                "page_size": 10,
                "direction": "BUY",
                "strategy_run_id": str(seed["strategy_run_id"]),
                "source_type": "live",
                "start_date": "2026-04-01T00:00:00Z",
                "end_date": "2026-04-01T23:59:59Z",
                "min_confidence": "0.8000",
            },
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["total"] == 1
    assert len(payload["data"]["items"]) == 1
    signal = payload["data"]["items"][0]
    assert signal["direction"] == "BUY"
    assert signal["strategy_name"] == "sentiment_momentum_v1"
    assert Decimal(signal["confidence"]) == Decimal("0.8200")
    assert Decimal(signal["price_at_signal"]) == Decimal("2310.00000000")


def test_invalid_query_param_returns_400_validation_error(db_session) -> None:
    _seed_core_api_data(db_session)

    response = asyncio.run(
        _request(
            db_session,
            "/api/v1/news",
            params={"start_date": "2026-04-01T10:00:00"},
        )
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_symbol_returns_400_validation_error(db_session) -> None:
    _seed_core_api_data(db_session)

    response = asyncio.run(
        _request(
            db_session,
            "/api/v1/sentiment/aggregate",
            params={"window": "4h", "symbol": "EURUSD"},
        )
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("path", ["/api/v1/news", "/api/v1/events", "/api/v1/signals"])
def test_start_date_after_end_date_returns_400_validation_error(db_session, path: str) -> None:
    _seed_core_api_data(db_session)

    response = asyncio.run(
        _request(
            db_session,
            path,
            params={
                "start_date": "2026-04-02T00:00:00Z",
                "end_date": "2026-04-01T00:00:00Z",
            },
        )
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_event_tag_type_returns_400_validation_error(db_session) -> None:
    _seed_core_api_data(db_session)

    response = asyncio.run(
        _request(
            db_session,
            "/api/v1/events",
            params={"tag_type": "unknown_tag"},
        )
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_method_not_allowed_uses_consistent_error_envelope(db_session) -> None:
    _seed_core_api_data(db_session)

    def override_db():
        yield db_session

    def override_viewer():
        return None

    app.dependency_overrides[get_session] = override_db
    app.dependency_overrides[require_viewer] = override_viewer
    transport = httpx.ASGITransport(app=app)
    try:
        async def _post() -> httpx.Response:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.post("/api/v1/news")

        response = asyncio.run(_post())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 405
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_news_id_returns_404_not_found(db_session) -> None:
    _seed_core_api_data(db_session)

    response = asyncio.run(_request(db_session, f"/api/v1/news/{uuid.uuid4()}"))

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "NOT_FOUND"
