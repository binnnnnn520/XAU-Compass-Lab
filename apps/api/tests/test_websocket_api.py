from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

from starlette.websockets import WebSocketDisconnect


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.main import app
from app.routes.websocket import handle_realtime_stream, realtime_stream
from app.services.price_feed import build_price_message
from app.services.price_feed.pubsub import (
    REALTIME_REDIS_CHANNEL,
    RedisRealtimePublisher,
    deserialize_realtime_message,
    realtime_channel_for_message,
    serialize_realtime_message,
)


class FakeWebSocket:
    def __init__(self, incoming: list[dict[str, object]]) -> None:
        self.incoming = list(incoming)
        self.sent: list[dict[str, object]] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def receive_json(self) -> dict[str, object]:
        if not self.incoming:
            raise WebSocketDisconnect()
        return self.incoming.pop(0)


class WaitingFakeWebSocket(FakeWebSocket):
    async def receive_json(self) -> dict[str, object]:
        if not self.incoming:
            await asyncio.sleep(0.01)
            raise WebSocketDisconnect()
        await asyncio.sleep(0)
        return self.incoming.pop(0)


class FakeRealtimeSubscriber:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages

    async def listen(self):
        await asyncio.sleep(0)
        for message in self.messages:
            yield message


class FakeRedisClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.closed = False

    def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1

    def close(self) -> None:
        self.closed = True


def test_websocket_stream_is_registered_under_api_v1() -> None:
    assert any(getattr(route, "path", None) == "/api/v1/ws/stream" for route in app.routes)


def test_websocket_stream_accepts_connection_and_acknowledges_subscriptions() -> None:
    websocket = FakeWebSocket(
        [
            {"type": "subscribe", "channels": ["prices", "risk_events"]},
            {"type": "ping"},
        ]
    )

    asyncio.run(realtime_stream(websocket))  # type: ignore[arg-type]

    assert websocket.accepted is True
    assert websocket.sent[0]["type"] == "connection.ready"
    assert websocket.sent[0]["data"]["subscriptions"] == ["prices", "signals", "risk_events"]
    assert websocket.sent[1]["type"] == "subscription.updated"
    assert websocket.sent[1]["data"]["subscriptions"] == ["prices", "risk_events"]
    assert websocket.sent[2]["type"] == "pong"


def test_websocket_stream_reports_unknown_subscription_channel() -> None:
    websocket = FakeWebSocket([{"type": "subscribe", "channels": ["prices", "orders"]}])

    asyncio.run(realtime_stream(websocket))  # type: ignore[arg-type]

    error = websocket.sent[1]
    assert error["type"] == "error"
    assert error["data"]["code"] == "UNKNOWN_CHANNEL"
    assert error["data"]["channels"] == ["orders"]


def test_price_feed_message_serializes_decimal_prices_as_strings() -> None:
    message = build_price_message(
        symbol="XAUUSD",
        timeframe="15m",
        price=Decimal("2321.12345678"),
        as_of=datetime(2026, 4, 30, 1, 15, tzinfo=UTC),
    )

    assert message == {
        "type": "price.updated",
        "timestamp": "2026-04-30T01:15:00+00:00",
        "data": {
            "symbol": "XAUUSD",
            "timeframe": "15m",
            "price": "2321.12345678",
        },
    }


def test_realtime_pubsub_serializes_and_deserializes_messages() -> None:
    message = build_price_message(
        symbol="XAUUSD",
        timeframe="15m",
        price=Decimal("2321.12345678"),
        as_of=datetime(2026, 4, 30, 1, 15, tzinfo=UTC),
    )

    payload = serialize_realtime_message(message)

    assert deserialize_realtime_message(payload) == message
    assert deserialize_realtime_message(payload.encode("utf-8")) == message
    assert deserialize_realtime_message("not json") is None
    assert realtime_channel_for_message(message) == "prices"


def test_realtime_pubsub_publisher_uses_configured_redis_channel() -> None:
    client = FakeRedisClient()
    publisher = RedisRealtimePublisher(
        redis_url="redis://redis.example:6379/0",
        client_factory=lambda _url: client,
    )
    message = build_price_message(
        symbol="XAUUSD",
        timeframe="15m",
        price=Decimal("2321.12345678"),
        as_of=datetime(2026, 4, 30, 1, 15, tzinfo=UTC),
    )

    published = publisher.publish(message)

    assert published == 1
    assert client.published == [(REALTIME_REDIS_CHANNEL, serialize_realtime_message(message))]
    assert client.closed is True


def test_websocket_stream_forwards_pubsub_messages_matching_subscription() -> None:
    price_message = build_price_message(
        symbol="XAUUSD",
        timeframe="15m",
        price=Decimal("2321.12345678"),
        as_of=datetime(2026, 4, 30, 1, 15, tzinfo=UTC),
    )
    websocket = WaitingFakeWebSocket([{"type": "subscribe", "channels": ["prices"]}])
    subscriber = FakeRealtimeSubscriber([price_message])

    asyncio.run(handle_realtime_stream(websocket, subscriber=subscriber))  # type: ignore[arg-type]

    assert price_message in websocket.sent


def test_websocket_stream_forwards_pubsub_messages_under_one_second() -> None:
    price_message = build_price_message(
        symbol="XAUUSD",
        timeframe="15m",
        price=Decimal("2321.12345678"),
        as_of=datetime(2026, 4, 30, 1, 15, tzinfo=UTC),
    )
    websocket = WaitingFakeWebSocket([{"type": "subscribe", "channels": ["prices"]}])
    subscriber = FakeRealtimeSubscriber([price_message])

    started_at = perf_counter()
    asyncio.run(handle_realtime_stream(websocket, subscriber=subscriber))  # type: ignore[arg-type]
    elapsed_seconds = perf_counter() - started_at

    assert price_message in websocket.sent
    assert elapsed_seconds < 1.0
