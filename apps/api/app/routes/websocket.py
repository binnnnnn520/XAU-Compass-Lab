from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.price_feed import (
    build_connection_ready,
    build_error,
    build_pong,
    build_subscription_updated,
    normalize_channels,
)
from app.services.price_feed.pubsub import (
    RedisRealtimeSubscriber,
    RealtimeSubscriber,
    realtime_channel_for_message,
)


router = APIRouter(tags=["websocket"])


@router.websocket("/ws/stream")
async def realtime_stream(websocket: WebSocket) -> None:
    await handle_realtime_stream(websocket, subscriber=RedisRealtimeSubscriber())


async def _forward_pubsub_messages(
    websocket: WebSocket,
    subscriptions: set[str],
    subscriber: RealtimeSubscriber,
) -> None:
    try:
        async for message in subscriber.listen():
            channel = realtime_channel_for_message(message)
            if channel in subscriptions:
                await websocket.send_json(message)
    except Exception:
        return


async def handle_realtime_stream(
    websocket: WebSocket,
    *,
    subscriber: RealtimeSubscriber | None = None,
) -> None:
    await websocket.accept()
    subscriptions, _unknown = normalize_channels(None)
    active_subscriptions = set(subscriptions)
    pubsub_task: asyncio.Task[None] | None = None
    if subscriber is not None:
        pubsub_task = asyncio.create_task(_forward_pubsub_messages(websocket, active_subscriptions, subscriber))

    await websocket.send_json(build_connection_ready(subscriptions))

    try:
        while True:
            payload = await websocket.receive_json()
            message_type = payload.get("type") if isinstance(payload, dict) else None
            if message_type == "ping":
                await websocket.send_json(build_pong())
                continue
            if message_type == "subscribe":
                raw_channels = payload.get("channels") if isinstance(payload, dict) else None
                channels, unknown = normalize_channels(raw_channels if isinstance(raw_channels, list) else [])
                if unknown:
                    await websocket.send_json(
                        build_error(
                            "UNKNOWN_CHANNEL",
                            "One or more realtime channels are not supported.",
                            channels=unknown,
                        )
                    )
                    continue
                subscriptions = channels
                active_subscriptions.clear()
                active_subscriptions.update(channels)
                await websocket.send_json(build_subscription_updated(subscriptions))
                continue

            await websocket.send_json(build_error("UNKNOWN_MESSAGE", "Unsupported realtime message type."))
    except WebSocketDisconnect:
        return
    finally:
        if pubsub_task is not None:
            pubsub_task.cancel()
            with suppress(asyncio.CancelledError):
                await pubsub_task
