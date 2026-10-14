from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.services.alt_data.cot_data import quantize_alt_data


@dataclass(frozen=True)
class DxyIndexBar:
    bar_time: datetime
    created_at: datetime
    close: Decimal


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("alternative data datetimes must be UTC-aware")
    return value.astimezone(UTC)


def available_dxy_bars(bars: list[DxyIndexBar], timestamp: datetime) -> list[DxyIndexBar]:
    normalized_timestamp = _as_utc(timestamp)
    available = [
        bar
        for bar in bars
        if _as_utc(bar.bar_time) < normalized_timestamp
        and _as_utc(bar.created_at) < normalized_timestamp
    ]
    return sorted(available, key=lambda bar: (_as_utc(bar.bar_time), _as_utc(bar.created_at)))


def dxy_momentum_1d(bars: list[DxyIndexBar], timestamp: datetime) -> Decimal:
    available = available_dxy_bars(bars, timestamp)
    if len(available) < 2:
        return Decimal("0.0000")
    latest = available[-1].close
    previous = available[-2].close
    if previous == Decimal("0"):
        return Decimal("0.0000")
    return quantize_alt_data((latest - previous) / previous)
