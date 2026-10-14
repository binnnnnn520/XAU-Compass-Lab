from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


SUPPORTED_CHANNELS = ("prices", "signals", "risk_events")


def _timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Realtime messages require UTC-aware timestamps.")
    return current.astimezone(UTC).isoformat()


def normalize_channels(raw_channels: list[object] | None) -> tuple[list[str], list[str]]:
    if raw_channels is None:
        return list(SUPPORTED_CHANNELS), []

    subscriptions: list[str] = []
    unknown: list[str] = []
    for raw_channel in raw_channels:
        channel = str(raw_channel)
        if channel in SUPPORTED_CHANNELS:
            if channel not in subscriptions:
                subscriptions.append(channel)
        elif channel not in unknown:
            unknown.append(channel)
    return subscriptions, unknown


def realtime_message(message_type: str, data: dict[str, Any], *, timestamp: datetime | None = None) -> dict[str, Any]:
    return {
        "type": message_type,
        "timestamp": _timestamp(timestamp),
        "data": data,
    }


def build_connection_ready(channels: list[str]) -> dict[str, Any]:
    return realtime_message("connection.ready", {"subscriptions": channels})


def build_subscription_updated(channels: list[str]) -> dict[str, Any]:
    return realtime_message("subscription.updated", {"subscriptions": channels})


def build_error(code: str, message: str, *, channels: list[str] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"code": code, "message": message}
    if channels is not None:
        data["channels"] = channels
    return realtime_message("error", data)


def build_pong() -> dict[str, Any]:
    return realtime_message("pong", {})


def build_price_message(
    *,
    symbol: str,
    timeframe: str,
    price: Decimal,
    as_of: datetime,
) -> dict[str, Any]:
    return realtime_message(
        "price.updated",
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "price": format(price, "f"),
        },
        timestamp=as_of,
    )
