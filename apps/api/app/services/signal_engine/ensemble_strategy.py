from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING, Any

from app.models import StrategyRun
from app.services.feature_engine import FeatureVector
from app.services.signal_engine.ml_strategy import DEFAULT_XGBOOST_STRATEGY_NAME
from app.services.signal_engine.rule_strategy import DEFAULT_STRATEGY_NAME
from app.services.signal_engine.strategy_interface import SignalDecision


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


SIGNAL_QUANTIZER = Decimal("0.0001")
DEFAULT_ENSEMBLE_STRATEGY_NAME = "ensemble_v1"
DEFAULT_MEMBER_WEIGHT = Decimal("1.0000")
DEFAULT_HOLD_CONFIDENCE = Decimal("0.2500")
SUPPORTED_MEMBER_STRATEGY_TYPES = {
    DEFAULT_STRATEGY_NAME,
    DEFAULT_XGBOOST_STRATEGY_NAME,
    "xgboost_gold_v1",
}


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SIGNAL_QUANTIZER, rounding=ROUND_HALF_UP)


def _hold(reason: str, confidence: Decimal = DEFAULT_HOLD_CONFIDENCE) -> SignalDecision:
    return SignalDecision(
        direction="HOLD",
        strength=Decimal("0.0000"),
        confidence=_quantize(confidence),
        reasoning=reason,
    )


def _as_decimal(value: Any, fallback: Decimal = DEFAULT_MEMBER_WEIGHT) -> Decimal | None:
    if value is None:
        return fallback
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _direction_score(direction: str) -> Decimal:
    normalized = direction.upper()
    if normalized == "BUY":
        return Decimal("1.0000")
    if normalized == "SELL":
        return Decimal("-1.0000")
    return Decimal("0.0000")


class EnsembleStrategy:
    strategy_name = DEFAULT_ENSEMBLE_STRATEGY_NAME

    def __init__(self, session: Session | None = None) -> None:
        self.session = session

    def generate_signal(self, features: FeatureVector, strategy_run: StrategyRun) -> SignalDecision:
        members = list((strategy_run.parameters or {}).get("members") or [])
        if not members:
            return _hold("ensemble_v1_no_members")

        total_weight = Decimal("0.0000")
        weighted_direction = Decimal("0.0000")
        weighted_strength = Decimal("0.0000")
        weighted_confidence = Decimal("0.0000")
        member_reasons: list[str] = []
        skipped_reasons: list[str] = []

        for member in members:
            if not isinstance(member, dict):
                skipped_reasons.append("invalid_member")
                continue

            member_weight = _as_decimal(member.get("weight"))
            if member_weight is None:
                skipped_reasons.append(f"invalid_weight={member.get('weight')}")
                continue
            if member_weight <= Decimal("0.0000"):
                skipped_reasons.append(f"non_positive_weight={member.get('weight')}")
                continue

            member_strategy_name = str(member.get("strategy_name") or member.get("strategy_type") or "").strip()
            member_strategy_type = str(member.get("strategy_type") or member_strategy_name).strip()
            if (
                member_strategy_name == DEFAULT_ENSEMBLE_STRATEGY_NAME
                or member_strategy_type == DEFAULT_ENSEMBLE_STRATEGY_NAME
            ):
                member_decision = _hold("ensemble_v1_recursive_member")
                member_strategy_name = DEFAULT_ENSEMBLE_STRATEGY_NAME
            elif member_strategy_type not in SUPPORTED_MEMBER_STRATEGY_TYPES:
                skipped_reasons.append(f"unsupported_member={member_strategy_type or '<missing>'}")
                continue
            else:
                member_parameters = dict(member.get("parameters") or {})
                member_parameters.setdefault("strategy_type", member_strategy_type)
                member_run = StrategyRun(
                    strategy_name=member_strategy_name,
                    version=str(member.get("version") or strategy_run.version),
                    parameters=member_parameters,
                )
                from app.services.signal_engine.model_registry import get_strategy_for_run

                member_strategy = get_strategy_for_run(member_run, session=self.session)
                member_decision = member_strategy.generate_signal(features, member_run)

            total_weight += member_weight
            weighted_direction += member_weight * _direction_score(member_decision.direction)
            weighted_strength += member_weight * member_decision.strength
            weighted_confidence += member_weight * member_decision.confidence
            member_reasons.append(f"{member_strategy_name}:{member_decision.direction}")

        if total_weight <= Decimal("0.0000"):
            reason = "ensemble_v1_no_valid_members"
            if skipped_reasons:
                reason = f"{reason} {' '.join(skipped_reasons)}"
            return _hold(reason)

        if weighted_direction > Decimal("0.0000"):
            direction = "BUY"
        elif weighted_direction < Decimal("0.0000"):
            direction = "SELL"
        else:
            direction = "HOLD"

        strength = weighted_strength / total_weight
        confidence = weighted_confidence / total_weight

        return SignalDecision(
            direction=direction,
            strength=_quantize(strength),
            confidence=_quantize(confidence),
            reasoning=(
                f"ensemble_v1 direction_score={_quantize(weighted_direction)} "
                f"members={','.join(member_reasons)}"
                f"{' skipped=' + ','.join(skipped_reasons) if skipped_reasons else ''}"
            ),
        )
