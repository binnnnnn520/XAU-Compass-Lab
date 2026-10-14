from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.models import StrategyRun
from app.services.feature_engine import FeatureVector
from app.services.signal_engine.strategy_interface import SignalDecision


SIGNAL_QUANTIZER = Decimal("0.0001")
DEFAULT_STRATEGY_NAME = "sentiment_momentum_v1"
DEFAULT_STRATEGY_VERSION = "1.0.0"
DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_STRATEGY_PARAMETERS: dict[str, object] = {
    "lookback_hours": DEFAULT_LOOKBACK_HOURS,
    "momentum_bars": 4,
    "positive_sentiment_threshold": "0.5000",
    "negative_sentiment_threshold": "-0.5000",
    "positive_momentum_threshold": "0.0001",
    "negative_momentum_threshold": "-0.0001",
}


def _as_decimal(value: object, fallback: str) -> Decimal:
    if value is None:
        return Decimal(fallback)
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SIGNAL_QUANTIZER, rounding=ROUND_HALF_UP)


class RuleStrategy:
    strategy_name = DEFAULT_STRATEGY_NAME

    def generate_signal(self, features: FeatureVector, strategy_run: StrategyRun) -> SignalDecision:
        parameters = strategy_run.parameters or {}
        positive_sentiment_threshold = _as_decimal(parameters.get("positive_sentiment_threshold"), "0.5000")
        negative_sentiment_threshold = _as_decimal(parameters.get("negative_sentiment_threshold"), "-0.5000")
        positive_momentum_threshold = _as_decimal(parameters.get("positive_momentum_threshold"), "0.0001")
        negative_momentum_threshold = _as_decimal(parameters.get("negative_momentum_threshold"), "-0.0001")

        if features.has_insufficient_data:
            return SignalDecision(
                direction="HOLD",
                strength=Decimal("0.0000"),
                confidence=Decimal("0.2500"),
                reasoning="insufficient_data",
            )

        direction = "HOLD"
        if (
            features.sentiment_mean > positive_sentiment_threshold
            and features.price_momentum_4h > positive_momentum_threshold
        ):
            direction = "BUY"
        elif (
            features.sentiment_mean < negative_sentiment_threshold
            and features.price_momentum_4h < negative_momentum_threshold
        ):
            direction = "SELL"

        strength = min(
            Decimal("1.0000"),
            abs(features.sentiment_mean) + min(Decimal("0.4000"), abs(features.price_momentum_4h) * Decimal("10")),
        )
        confidence = min(
            Decimal("0.9900"),
            Decimal("0.4500")
            + min(Decimal("0.3000"), abs(features.sentiment_mean) / Decimal("2"))
            + min(Decimal("0.2400"), Decimal(features.event_count) * Decimal("0.0400")),
        )

        if direction == "HOLD":
            reasoning = "thresholds_not_met"
        else:
            reasoning = (
                f"{direction.lower()} because sentiment_mean={features.sentiment_mean} "
                f"and price_momentum_4h={features.price_momentum_4h}"
            )

        return SignalDecision(
            direction=direction,
            strength=_quantize(strength),
            confidence=_quantize(confidence),
            reasoning=reasoning,
        )
