from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import suppress
import json
from typing import Any, Protocol

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError

from app.config import get_settings


REALTIME_REDIS_CHANNEL = "gold_agent.realtime"


class RealtimeSubscriber(Protocol):
    def listen(self) -> AsyncIterator[dict[str, Any]]:
        ...


class RedisClient(Protocol):
    def publish(self, channel: str, payload: str) -> int:
        ...

    def close(self) -> None:
        ...


RedisClientFactory = Callable[[str], RedisClient]
AsyncRedisClientFactory = Callable[[str], AsyncRedis]


def serialize_realtime_message(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"), sort_keys=True)


def deserialize_realtime_message(payload: str | bytes) -> dict[str, Any] | None:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")

    try:
        message = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None

    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        return None

    return message


def realtime_channel_for_message(message: dict[str, Any]) -> str | None:
    message_type = str(message.get("type", ""))
    if message_type.startswith("price."):
        return "prices"
    if message_type.startswith("signal."):
        return "signals"
    if message_type.startswith("risk."):
        return "risk_events"
    return None


class RedisRealtimePublisher:
    def __init__(
        self,
        *,
        redis_url: str | None = None,
        channel: str = REALTIME_REDIS_CHANNEL,
        client_factory: RedisClientFactory | None = None,
    ) -> None:
        self.redis_url = redis_url or get_settings().redis_url
        self.channel = channel
        self.client_factory = client_factory or (lambda url: Redis.from_url(url, decode_responses=True))

    def publish(self, message: dict[str, Any]) -> int:
        client = self.client_factory(self.redis_url)
        try:
            return int(client.publish(self.channel, serialize_realtime_message(message)))
        finally:
            client.close()


class RedisRealtimeSubscriber:
    def __init__(
        self,
        *,
        redis_url: str | None = None,
        channel: str = REALTIME_REDIS_CHANNEL,
        client_factory: AsyncRedisClientFactory | None = None,
    ) -> None:
        self.redis_url = redis_url or get_settings().redis_url
        self.channel = channel
        self.client_factory = client_factory or (lambda url: AsyncRedis.from_url(url, decode_responses=False))

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        client = self.client_factory(self.redis_url)
        pubsub = client.pubsub()

        try:
            await pubsub.subscribe(self.channel)
            async for event in pubsub.listen():
                if event.get("type") != "message":
                    continue
                message = deserialize_realtime_message(event.get("data", b""))
                if message is not None:
                    yield message
        except RedisError:
            return
        finally:
            with suppress(Exception):
                await pubsub.unsubscribe(self.channel)
            with suppress(Exception):
                await pubsub.close()
            with suppress(Exception):
                await client.aclose()
