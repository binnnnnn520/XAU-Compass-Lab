from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sys

import httpx


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.auth.dependencies import require_viewer
from app.database import get_session
from app.main import app
from app.models import MarketBar, NewsItem, SentimentScore, Signal, StrategyRun
from app.services.paper_execution import execute_signal


def _market_bar(*, timestamp: datetime, price: str) -> MarketBar:
    value = Decimal(price)
    return MarketBar(
        timeframe="1h",
        bar_time=timestamp,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("10.00000000"),
    )


def _signal(*, strategy: StrategyRun, timestamp: datetime, direction: str, price: str) -> Signal:
    return Signal(
        strategy_run_id=strategy.id,
        signal_time=timestamp,
        direction=direction,
        strength=Decimal("0.8000"),
        confidence=Decimal("0.7600"),
        price_at_signal=Decimal(price),
        features_used={"sentiment_mean": "0.2000"},
        reasoning="API fixture",
    )


async def _request(
    db_session,
    method: str,
    path: str,
    *,
    params: dict[str, object] | None = None,
) -> httpx.Response:
    def override_db():
        yield db_session

    def override_viewer():
        return None

    app.dependency_overrides[get_session] = override_db
    app.dependency_overrides[require_viewer] = override_viewer
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, params=params)
    finally:
        app.dependency_overrides.clear()


def test_paper_and_risk_read_endpoints(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="paper_api_v1",
        version="1.0.0",
        parameters={"paper": {"initial_capital": "100000.00", "order_quantity": "1.00000000"}},
        is_active=True,
    )
    filled_time = datetime(2026, 4, 8, 13, 0, tzinfo=UTC)
    rejected_time = filled_time + timedelta(hours=1)
    db_session.add(strategy)
    db_session.commit()
    db_session.add_all(
        [
            _market_bar(timestamp=filled_time, price="2299.00000000"),
            _market_bar(timestamp=rejected_time, price="2285.00000000"),
        ]
    )
    for index in range(5):
        item = NewsItem(
            title=f"API negative {index}",
            published_at=rejected_time - timedelta(minutes=5 * (index + 1)),
            title_hash=f"a{index}".ljust(64, "0"),
            status="analyzed",
        )
        sentiment = SentimentScore(
            news_item=item,
            analyzer_type=f"api_rule_{index}",
            sentiment="negative",
            score=Decimal("-0.9000"),
            confidence=Decimal("0.9000"),
            created_at=rejected_time - timedelta(minutes=5 * (index + 1)),
        )
        db_session.add_all([item, sentiment])
    db_session.commit()

    filled_signal = _signal(strategy=strategy, timestamp=filled_time, direction="BUY", price="2299.00000000")
    rejected_signal = _signal(strategy=strategy, timestamp=rejected_time, direction="BUY", price="2285.00000000")
    db_session.add_all([filled_signal, rejected_signal])
    db_session.commit()

    execute_signal(db_session, filled_signal.id)
    execute_signal(db_session, rejected_signal.id)
    db_session.commit()

    orders_response = asyncio.run(
        _request(db_session, "GET", "/api/v1/paper/orders", params={"status": "filled", "page": 1, "page_size": 10})
    )
    assert orders_response.status_code == 200
    orders_payload = orders_response.json()
    assert orders_payload["success"] is True
    assert orders_payload["data"]["total"] == 1
    assert orders_payload["data"]["items"][0]["status"] == "filled"

    positions_response = asyncio.run(
        _request(db_session, "GET", "/api/v1/paper/positions", params={"status": "open", "page": 1, "page_size": 10})
    )
    assert positions_response.status_code == 200
    positions_payload = positions_response.json()
    assert positions_payload["success"] is True
    assert positions_payload["data"]["total"] == 1
    assert positions_payload["data"]["items"][0]["side"] == "LONG"

    account_response = asyncio.run(_request(db_session, "GET", "/api/v1/paper/account"))
    assert account_response.status_code == 200
    account_payload = account_response.json()
    assert account_payload["success"] is True
    assert account_payload["data"]["open_positions"] == 1

    events_response = asyncio.run(
        _request(
            db_session,
            "GET",
            "/api/v1/risk/events",
            params={"severity": "critical", "page": 1, "page_size": 10},
        )
    )
    assert events_response.status_code == 200
    events_payload = events_response.json()
    assert events_payload["success"] is True
    assert events_payload["data"]["total"] >= 1
    assert events_payload["data"]["items"][0]["event_type"] == "circuit_breaker"

    status_response = asyncio.run(_request(db_session, "GET", "/api/v1/risk/status"))
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["success"] is True
    assert "trading_enabled" in status_payload["data"]
    assert "circuit_breaker_active" in status_payload["data"]


def test_risk_events_endpoint_rejects_naive_datetime_filters(db_session) -> None:
    response = asyncio.run(
        _request(db_session, "GET", "/api/v1/risk/events", params={"start_date": "2026-04-08T13:00:00"})
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
