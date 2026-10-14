from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models import Signal, StrategyRun
from app.services.calibration import calibrate_confidence_from_parameters
from app.services.feature_engine import FeatureVector, compute_features
from app.services.signal_engine.model_registry import get_strategy_for_run
from app.services.signal_engine.rule_strategy import (
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_STRATEGY_NAME,
    DEFAULT_STRATEGY_PARAMETERS,
    DEFAULT_STRATEGY_VERSION,
)
from app.services.signal_engine.strategy_interface import SignalDecision


def _normalize_signal_timestamp(timestamp: datetime | None) -> datetime:
    if timestamp is None:
        return utcnow().astimezone(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be UTC-aware")
    return timestamp.astimezone(UTC)


def ensure_default_strategy_run(session: Session) -> StrategyRun:
    active_strategy = session.execute(
        select(StrategyRun).where(StrategyRun.is_active.is_(True)).order_by(StrategyRun.created_at.asc())
    ).scalar_one_or_none()
    if active_strategy is not None:
        return active_strategy

    strategy = session.execute(
        select(StrategyRun)
        .where(
            StrategyRun.strategy_name == DEFAULT_STRATEGY_NAME,
            StrategyRun.version == DEFAULT_STRATEGY_VERSION,
        )
        .order_by(StrategyRun.created_at.asc())
    ).scalar_one_or_none()
    if strategy is None:
        strategy = StrategyRun(
            strategy_name=DEFAULT_STRATEGY_NAME,
            version=DEFAULT_STRATEGY_VERSION,
            parameters=dict(DEFAULT_STRATEGY_PARAMETERS),
            description="Default Task 6 sentiment and momentum strategy.",
            is_active=True,
        )
        session.add(strategy)
        session.flush()
        return strategy

    strategy.is_active = True
    session.add(strategy)
    session.flush()
    return strategy


def generate_signal(features: FeatureVector, strategy_run: StrategyRun, session: Session | None = None) -> SignalDecision:
    strategy = get_strategy_for_run(strategy_run, session)
    decision = strategy.generate_signal(features, strategy_run)
    calibrated_confidence = calibrate_confidence_from_parameters(decision.confidence, strategy_run.parameters or {})
    if calibrated_confidence is None:
        return decision
    return SignalDecision(
        direction=decision.direction,
        strength=decision.strength,
        confidence=calibrated_confidence,
        reasoning=f"{decision.reasoning}; confidence_calibrated",
    )


def generate_signals_for_timestamp(
    session: Session,
    *,
    symbol: str = "XAUUSD",
    timestamp: datetime | None = None,
    source_type: str = "live",
) -> list[Signal]:
    signal_timestamp = _normalize_signal_timestamp(timestamp)
    active_strategies = session.execute(
        select(StrategyRun).where(StrategyRun.is_active.is_(True)).order_by(StrategyRun.created_at.asc())
    ).scalars().all()

    if not active_strategies:
        active_strategies = [ensure_default_strategy_run(session)]

    persisted_signals: list[Signal] = []
    for strategy in active_strategies:
        parameters = strategy.parameters or {}
        lookback_hours = int(parameters.get("lookback_hours", DEFAULT_LOOKBACK_HOURS))
        momentum_bars = int(parameters.get("momentum_bars", 4))
        features = compute_features(
            session,
            symbol,
            signal_timestamp,
            lookback_hours,
            momentum_bars=momentum_bars,
        )
        decision = generate_signal(features, strategy, session=session)
        signal = Signal(
            strategy_run_id=strategy.id,
            symbol=symbol,
            signal_time=signal_timestamp,
            direction=decision.direction,
            strength=decision.strength,
            confidence=decision.confidence,
            price_at_signal=features.latest_price,
            features_used=features.snapshot(),
            reasoning=decision.reasoning,
            source_type=source_type,
        )
        session.add(signal)
        session.flush()
        persisted_signals.append(signal)

    return persisted_signals
