from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext


FEATURE_QUANTIZER = Decimal("0.0001")
ZERO = Decimal("0.0000")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(FEATURE_QUANTIZER, rounding=ROUND_HALF_UP)


def sentiment_std(scores: list[Decimal]) -> Decimal:
    if len(scores) < 2:
        return ZERO
    mean = sum(scores, ZERO) / Decimal(len(scores))
    variance = sum((score - mean) ** 2 for score in scores) / Decimal(len(scores))
    return _quantize(_sqrt_decimal(variance))


def sentiment_velocity(scores: list[Decimal], timestamps: list[datetime]) -> Decimal:
    if len(scores) < 2 or len(scores) != len(timestamps):
        return ZERO

    ordered = sorted(zip(timestamps, scores, strict=False), key=lambda item: item[0])
    first_timestamp, first_score = ordered[0]
    last_timestamp, last_score = ordered[-1]
    elapsed = last_timestamp - first_timestamp
    elapsed_microseconds = (
        ((elapsed.days * 24 * 60 * 60) + elapsed.seconds) * 1_000_000
        + elapsed.microseconds
    )
    if elapsed_microseconds <= 0:
        return ZERO
    hours = Decimal(elapsed_microseconds) / Decimal("3600000000")
    if hours == Decimal("0"):
        return ZERO
    return _quantize((last_score - first_score) / hours)


def _sqrt_decimal(value: Decimal) -> Decimal:
    if value <= Decimal("0"):
        return ZERO
    with localcontext() as context:
        context.prec = 28
        return +value.sqrt(context)
