from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext


FEATURE_QUANTIZER = Decimal("0.0001")
ZERO = Decimal("0.0000")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(FEATURE_QUANTIZER, rounding=ROUND_HALF_UP)


def sma(values: list[Decimal], period: int) -> Decimal:
    if period <= 0 or len(values) < period:
        return ZERO
    window = values[-period:]
    return _quantize(sum(window, ZERO) / Decimal(period))


def ema(values: list[Decimal], period: int) -> Decimal:
    series = _ema_series(values, period)
    return series[-1] if series else ZERO


def rsi(closes: list[Decimal], period: int = 14) -> Decimal:
    if period <= 0 or len(closes) < period + 1:
        return ZERO

    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = [max(change, Decimal("0")) for change in changes[-period:]]
    losses = [max(-change, Decimal("0")) for change in changes[-period:]]
    average_gain = sum(gains, ZERO) / Decimal(period)
    average_loss = sum(losses, ZERO) / Decimal(period)
    if average_loss == Decimal("0"):
        return _quantize(Decimal("100"))
    relative_strength = average_gain / average_loss
    return _quantize(Decimal("100") - (Decimal("100") / (Decimal("1") + relative_strength)))


def macd(
    closes: list[Decimal],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[Decimal, Decimal, Decimal]:
    if fast <= 0 or slow <= 0 or signal <= 0 or fast >= slow or len(closes) < slow + signal:
        return ZERO, ZERO, ZERO

    fast_series = _ema_series(closes, fast)
    slow_series = _ema_series(closes, slow)
    if not fast_series or not slow_series:
        return ZERO, ZERO, ZERO

    aligned_fast = fast_series[-len(slow_series) :]
    macd_series = [fast_value - slow_value for fast_value, slow_value in zip(aligned_fast, slow_series, strict=False)]
    signal_series = _ema_series(macd_series, signal)
    if not signal_series:
        return _quantize(macd_series[-1]), ZERO, ZERO

    macd_line = _quantize(macd_series[-1])
    signal_line = _quantize(signal_series[-1])
    histogram = _quantize(macd_series[-1] - signal_series[-1])
    return macd_line, signal_line, histogram


def bollinger_bands(
    closes: list[Decimal],
    period: int = 20,
    std_dev: int = 2,
) -> tuple[Decimal, Decimal, Decimal]:
    if period <= 0 or std_dev <= 0 or len(closes) < period:
        return ZERO, ZERO, ZERO

    window = closes[-period:]
    middle = sum(window, ZERO) / Decimal(period)
    variance = sum((value - middle) ** 2 for value in window) / Decimal(period)
    standard_deviation = _sqrt_decimal(variance)
    offset = standard_deviation * Decimal(std_dev)
    upper = _quantize(middle + offset)
    lower = _quantize(middle - offset)
    return upper, _quantize(middle), lower


def bollinger_position(close: Decimal, upper: Decimal, lower: Decimal) -> Decimal:
    if upper <= lower:
        return _quantize(Decimal("0.5000"))
    position = (close - lower) / (upper - lower)
    clamped = min(Decimal("1"), max(Decimal("0"), position))
    return _quantize(clamped)


def bollinger_width(upper: Decimal, lower: Decimal, middle: Decimal) -> Decimal:
    if middle == Decimal("0"):
        return ZERO
    return _quantize((upper - lower) / middle)


def atr(
    highs: list[Decimal],
    lows: list[Decimal],
    closes: list[Decimal],
    period: int = 14,
) -> Decimal:
    if period <= 0 or len(highs) != len(lows) or len(highs) != len(closes) or len(closes) < period + 1:
        return ZERO

    true_ranges: list[Decimal] = []
    for index in range(1, len(closes)):
        high = highs[index]
        low = lows[index]
        previous_close = closes[index - 1]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))

    if len(true_ranges) < period:
        return ZERO
    return _quantize(sum(true_ranges[-period:], ZERO) / Decimal(period))


def price_distance(price: Decimal, ma_value: Decimal) -> Decimal:
    if ma_value == Decimal("0"):
        return ZERO
    return _quantize((price - ma_value) / ma_value)


def volume_ratio(volumes: list[Decimal], period: int = 20) -> Decimal:
    if period <= 0 or len(volumes) < period:
        return ZERO
    baseline = sum(volumes[-period:], ZERO) / Decimal(period)
    if baseline == Decimal("0"):
        return ZERO
    return _quantize(volumes[-1] / baseline)


def _ema_series(values: list[Decimal], period: int) -> list[Decimal]:
    if period <= 0 or len(values) < period:
        return []

    smoothing = Decimal("2") / Decimal(period + 1)
    current = sum(values[:period], ZERO) / Decimal(period)
    series = [_quantize(current)]
    for value in values[period:]:
        current = ((value - current) * smoothing) + current
        series.append(_quantize(current))
    return series


def _sqrt_decimal(value: Decimal) -> Decimal:
    if value <= Decimal("0"):
        return ZERO
    with localcontext() as context:
        context.prec = 28
        return +value.sqrt(context)
