from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    from app.models import StrategyRun
    from app.services.feature_engine import FeatureVector


@dataclass(frozen=True)
class SignalDecision:
    direction: str
    strength: Decimal
    confidence: Decimal
    reasoning: str


@runtime_checkable
class StrategyInterface(Protocol):
    strategy_name: str

    def generate_signal(self, features: FeatureVector, strategy_run: StrategyRun) -> SignalDecision:
        ...
