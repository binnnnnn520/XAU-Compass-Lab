from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditLog, LiveParallelObservation, PaperOrder, RiskEvent


MONEY_QUANTIZER = Decimal("0.00000001")
RATIO_QUANTIZER = Decimal("0.0001")
DEFAULT_DAILY_NOTIONAL_LIMIT = Decimal("0.00000000")
DEFAULT_MAX_INITIAL_CAPITAL_FRACTION = Decimal("0.0100")
BPS_MULTIPLIER = Decimal("10000")


@dataclass(frozen=True)
class LiveReadinessConfig:
    enabled: bool = False
    kill_switch_enabled: bool = True
    manual_approval_required: bool = True
    daily_notional_limit: Decimal = DEFAULT_DAILY_NOTIONAL_LIMIT
    max_initial_capital_fraction: Decimal = DEFAULT_MAX_INITIAL_CAPITAL_FRACTION
    real_broker_routing_enabled: bool = False


@dataclass(frozen=True)
class LiveOrderRequest:
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    price: Decimal
    confidence: Decimal
    daily_notional_so_far: Decimal
    total_equity: Decimal


@dataclass(frozen=True)
class LiveReadinessDecision:
    passed: bool
    requires_manual_approval: bool
    reject_reason: str | None
    checks: dict[str, object]


@dataclass(frozen=True)
class LiveBrokerRoutingRequest:
    broker_name: str
    credentials_configured: bool
    manual_approval_id: str | None
    approval_actor: str | None
    approved_at: datetime | None


@dataclass(frozen=True)
class LiveBrokerRoutingDecision:
    passed: bool
    reject_reason: str | None
    checks: dict[str, object]


@dataclass(frozen=True)
class LiveEmergencyStopResult:
    kill_switch_enabled: bool
    real_broker_routing_enabled: bool
    close_all_positions_requested: bool
    close_position_count: int
    audit_log_id: UUID
    risk_event_id: UUID
    requested_at: datetime


@dataclass(frozen=True)
class ParallelRunObservation:
    signal_id: str
    signal_time: datetime
    paper_direction: str
    live_direction: str
    paper_order_time: datetime
    live_order_time: datetime
    paper_fill_price: Decimal
    live_fill_price: Decimal


@dataclass(frozen=True)
class PaperLiveDivergenceReport:
    observation_count: int
    direction_divergence_count: int
    direction_divergence_rate: Decimal
    average_latency_delta_seconds: Decimal
    average_slippage_bps: Decimal
    sharpe_deviation: Decimal
    running_days: Decimal
    risk_event_count: int
    can_promote_capital: bool


@dataclass(frozen=True)
class GrayReleaseReportSnapshot:
    generated_at: datetime
    observation_count: int
    direction_divergence_count: int
    direction_divergence_rate: Decimal
    average_latency_delta_seconds: Decimal
    average_slippage_bps: Decimal
    sharpe_deviation: Decimal
    running_days: Decimal
    risk_event_count: int
    can_promote_capital: bool
    evidence_window_started: bool
    acceptance_ready: bool
    acceptance_blockers: list[str]


@dataclass(frozen=True)
class ParallelObservationCollectionResult:
    observed_count: int
    skipped_count: int
    as_of: datetime


def _quantize_money(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def _quantize_ratio(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(RATIO_QUANTIZER, rounding=ROUND_HALF_UP)


def _serialize_decimal(value: Decimal) -> str:
    return format(value, "f")


def _serialize_audit_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _serialize_decimal(value)
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, dict):
        return {str(key): _serialize_audit_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_audit_value(item) for item in value]
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("live readiness datetimes must be UTC-aware")
    return value.astimezone(UTC)


def _slippage_bps(paper_price: Decimal, live_price: Decimal) -> Decimal:
    if paper_price == Decimal("0"):
        return Decimal("0.0000")
    return _quantize_ratio(abs(live_price - paper_price) / paper_price * BPS_MULTIPLIER)


def _decimal_from(container: dict[str, Any], key: str, default: Decimal) -> Decimal:
    value = container.get(key)
    return default if value is None else Decimal(str(value))


def load_live_readiness_config(parameters: dict[str, Any] | None) -> LiveReadinessConfig:
    raw_parameters = parameters or {}
    live_parameters = raw_parameters.get("live", {})
    if not isinstance(live_parameters, dict):
        live_parameters = {}

    enabled = bool(live_parameters.get("enabled", False))
    kill_switch_enabled = bool(live_parameters.get("kill_switch_enabled", True))
    real_broker_routing_enabled = bool(live_parameters.get("real_broker_routing_enabled", False))
    return LiveReadinessConfig(
        enabled=enabled,
        kill_switch_enabled=kill_switch_enabled,
        manual_approval_required=True,
        daily_notional_limit=_quantize_money(
            _decimal_from(live_parameters, "daily_notional_limit", DEFAULT_DAILY_NOTIONAL_LIMIT)
        ),
        max_initial_capital_fraction=_quantize_ratio(
            _decimal_from(live_parameters, "max_initial_capital_fraction", DEFAULT_MAX_INITIAL_CAPITAL_FRACTION)
        ),
        real_broker_routing_enabled=real_broker_routing_enabled,
    )


def record_live_readiness_setting_change(
    session: Session,
    *,
    actor: str,
    setting_name: str,
    old_value: Any,
    new_value: Any,
    reason: str,
    changed_at: datetime,
    ip_address: str | None = None,
) -> AuditLog:
    changed_at_utc = _as_utc(changed_at)
    audit_log = AuditLog(
        action="live_readiness_setting_changed",
        entity_type="live_readiness",
        entity_id=None,
        actor=actor,
        old_value={
            "setting_name": setting_name,
            "value": _serialize_audit_value(old_value),
        },
        new_value={
            "setting_name": setting_name,
            "value": _serialize_audit_value(new_value),
            "reason": reason,
            "changed_at": changed_at_utc.isoformat(),
        },
        ip_address=ip_address,
    )
    session.add(audit_log)
    session.flush()
    return audit_log


def trigger_live_emergency_stop(
    session: Session,
    *,
    actor: str,
    reason: str,
    requested_at: datetime,
    open_live_position_ids: list[str] | None = None,
    ip_address: str | None = None,
) -> LiveEmergencyStopResult:
    requested_at_utc = _as_utc(requested_at)
    position_ids = list(open_live_position_ids or [])
    event_metadata = {
        "requested_at": requested_at_utc.isoformat(),
        "open_live_position_ids": position_ids,
        "close_all_positions_requested": True,
        "real_broker_routing_enabled": False,
        "kill_switch_enabled": True,
    }
    risk_event = RiskEvent(
        event_type="live_emergency_stop",
        severity="critical",
        trigger_value=None,
        threshold_value=None,
        action_taken="halt_trading_and_request_position_close",
        related_order_id=None,
        description=reason,
        metadata_json=event_metadata,
    )
    session.add(risk_event)
    session.flush()

    audit_log = AuditLog(
        action="live_emergency_stop_triggered",
        entity_type="live_readiness",
        entity_id=None,
        actor=actor,
        old_value=None,
        new_value={
            **event_metadata,
            "reason": reason,
            "risk_event_id": str(risk_event.id),
        },
        ip_address=ip_address,
    )
    session.add(audit_log)
    session.flush()

    return LiveEmergencyStopResult(
        kill_switch_enabled=True,
        real_broker_routing_enabled=False,
        close_all_positions_requested=True,
        close_position_count=len(position_ids),
        audit_log_id=audit_log.id,
        risk_event_id=risk_event.id,
        requested_at=requested_at_utc,
    )


def evaluate_live_order_readiness(
    config: LiveReadinessConfig,
    request: LiveOrderRequest,
) -> LiveReadinessDecision:
    order_notional = _quantize_money(request.quantity * request.price)
    projected_daily_notional = _quantize_money(request.daily_notional_so_far + order_notional)
    max_order_notional = _quantize_money(request.total_equity * config.max_initial_capital_fraction)
    checks: dict[str, object] = {
        "enabled": config.enabled,
        "kill_switch_enabled": config.kill_switch_enabled,
        "manual_approval_required": True,
        "order_notional": _serialize_decimal(order_notional),
        "projected_daily_notional": _serialize_decimal(projected_daily_notional),
        "daily_notional_limit": _serialize_decimal(config.daily_notional_limit),
        "max_order_notional": _serialize_decimal(max_order_notional),
        "max_initial_capital_fraction": _serialize_decimal(config.max_initial_capital_fraction),
    }

    if not config.enabled:
        return LiveReadinessDecision(
            passed=False,
            requires_manual_approval=True,
            reject_reason="live_trading_disabled",
            checks=checks,
        )
    if config.kill_switch_enabled:
        return LiveReadinessDecision(
            passed=False,
            requires_manual_approval=True,
            reject_reason="kill_switch_enabled",
            checks=checks,
        )
    if config.daily_notional_limit <= Decimal("0") or projected_daily_notional > config.daily_notional_limit:
        return LiveReadinessDecision(
            passed=False,
            requires_manual_approval=True,
            reject_reason="daily_notional_limit_exceeded",
            checks=checks,
        )
    if order_notional > max_order_notional:
        return LiveReadinessDecision(
            passed=False,
            requires_manual_approval=True,
            reject_reason="initial_capital_fraction_exceeded",
            checks=checks,
        )
    return LiveReadinessDecision(
        passed=True,
        requires_manual_approval=True,
        reject_reason=None,
        checks=checks,
    )


def evaluate_live_broker_routing(
    config: LiveReadinessConfig,
    readiness_decision: LiveReadinessDecision,
    request: LiveBrokerRoutingRequest,
) -> LiveBrokerRoutingDecision:
    approved_at = _as_utc(request.approved_at).isoformat() if request.approved_at is not None else None
    checks: dict[str, object] = {
        "broker_name": request.broker_name,
        "real_broker_routing_enabled": config.real_broker_routing_enabled,
        "order_readiness_passed": readiness_decision.passed,
        "credentials_configured": request.credentials_configured,
        "manual_approval_id": request.manual_approval_id,
        "approval_actor": request.approval_actor,
        "approved_at": approved_at,
    }

    if not config.real_broker_routing_enabled:
        return LiveBrokerRoutingDecision(
            passed=False,
            reject_reason="real_broker_routing_disabled",
            checks=checks,
        )
    if not readiness_decision.passed:
        return LiveBrokerRoutingDecision(
            passed=False,
            reject_reason="live_readiness_failed",
            checks=checks,
        )
    if not request.manual_approval_id or not request.approval_actor or approved_at is None:
        return LiveBrokerRoutingDecision(
            passed=False,
            reject_reason="manual_approval_missing",
            checks=checks,
        )
    if not request.credentials_configured:
        return LiveBrokerRoutingDecision(
            passed=False,
            reject_reason="broker_credentials_missing",
            checks=checks,
        )
    return LiveBrokerRoutingDecision(
        passed=True,
        reject_reason=None,
        checks=checks,
    )


def build_paper_live_divergence_report(
    observations: list[ParallelRunObservation],
    *,
    running_days: Decimal = Decimal("0.0000"),
    risk_event_count: int = 0,
    paper_sharpe: Decimal = Decimal("0.0000"),
    live_sharpe: Decimal = Decimal("0.0000"),
) -> PaperLiveDivergenceReport:
    observation_count = len(observations)
    if observation_count == 0:
        return PaperLiveDivergenceReport(
            observation_count=0,
            direction_divergence_count=0,
            direction_divergence_rate=Decimal("0.0000"),
            average_latency_delta_seconds=Decimal("0.0000"),
            average_slippage_bps=Decimal("0.0000"),
            sharpe_deviation=Decimal("0.0000"),
            running_days=_quantize_ratio(running_days),
            risk_event_count=risk_event_count,
            can_promote_capital=False,
        )

    direction_divergence_count = 0
    latency_total = Decimal("0.0000")
    slippage_total = Decimal("0.0000")
    for observation in observations:
        _as_utc(observation.signal_time)
        paper_order_time = _as_utc(observation.paper_order_time)
        live_order_time = _as_utc(observation.live_order_time)
        direction_divergence_count += int(observation.paper_direction != observation.live_direction)
        latency_total += Decimal(str(abs((live_order_time - paper_order_time).total_seconds())))
        slippage_total += _slippage_bps(observation.paper_fill_price, observation.live_fill_price)

    direction_divergence_rate = _quantize_ratio(
        Decimal(direction_divergence_count) / Decimal(observation_count)
    )
    average_latency_delta_seconds = _quantize_ratio(latency_total / Decimal(observation_count))
    average_slippage_bps = _quantize_ratio(slippage_total / Decimal(observation_count))
    sharpe_deviation = (
        Decimal("0.0000")
        if paper_sharpe == Decimal("0")
        else _quantize_ratio(abs(paper_sharpe - live_sharpe) / abs(paper_sharpe))
    )
    can_promote_capital = (
        _quantize_ratio(running_days) >= Decimal("14.0000")
        and risk_event_count == 0
        and sharpe_deviation < Decimal("0.2000")
        and direction_divergence_count == 0
    )

    return PaperLiveDivergenceReport(
        observation_count=observation_count,
        direction_divergence_count=direction_divergence_count,
        direction_divergence_rate=direction_divergence_rate,
        average_latency_delta_seconds=average_latency_delta_seconds,
        average_slippage_bps=average_slippage_bps,
        sharpe_deviation=sharpe_deviation,
        running_days=_quantize_ratio(running_days),
        risk_event_count=risk_event_count,
        can_promote_capital=can_promote_capital,
    )


def record_parallel_run_observation(
    session: Session,
    *,
    signal_id: str,
    symbol: str,
    signal_time: datetime,
    paper_direction: str,
    live_direction: str,
    paper_order_time: datetime,
    live_order_time: datetime,
    paper_fill_price: Decimal,
    live_fill_price: Decimal,
    order_notional: Decimal,
    dry_run_status: str,
    guard_passed: bool,
    risk_event_count: int,
    observed_at: datetime,
    metadata: dict[str, Any] | None = None,
) -> LiveParallelObservation:
    if risk_event_count < 0:
        raise ValueError("risk_event_count must be non-negative")

    observation = LiveParallelObservation(
        signal_id=signal_id,
        symbol=symbol,
        signal_time=_as_utc(signal_time),
        paper_direction=paper_direction,
        live_direction=live_direction,
        paper_order_time=_as_utc(paper_order_time),
        live_order_time=_as_utc(live_order_time),
        paper_fill_price=_quantize_money(paper_fill_price),
        live_fill_price=_quantize_money(live_fill_price),
        order_notional=_quantize_money(order_notional),
        dry_run_status=dry_run_status,
        guard_passed=guard_passed,
        risk_event_count=risk_event_count,
        observed_at=_as_utc(observed_at),
        metadata_json=_serialize_audit_value(metadata or {}),
    )
    session.add(observation)
    session.flush()
    return observation


def build_persisted_parallel_run_report(
    session: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    paper_sharpe: Decimal = Decimal("0.0000"),
    live_sharpe: Decimal = Decimal("0.0000"),
) -> PaperLiveDivergenceReport:
    statement = select(LiveParallelObservation).order_by(LiveParallelObservation.signal_time.asc())
    if start_at is not None:
        statement = statement.where(LiveParallelObservation.signal_time >= _as_utc(start_at))
    if end_at is not None:
        statement = statement.where(LiveParallelObservation.signal_time <= _as_utc(end_at))

    persisted_observations = session.execute(statement).scalars().all()
    observations = [
        ParallelRunObservation(
            signal_id=row.signal_id,
            signal_time=row.signal_time,
            paper_direction=row.paper_direction,
            live_direction=row.live_direction,
            paper_order_time=row.paper_order_time,
            live_order_time=row.live_order_time,
            paper_fill_price=row.paper_fill_price,
            live_fill_price=row.live_fill_price,
        )
        for row in persisted_observations
    ]
    risk_event_count = sum(row.risk_event_count for row in persisted_observations)
    running_days = _parallel_running_days(persisted_observations)
    return build_paper_live_divergence_report(
        observations,
        running_days=running_days,
        risk_event_count=risk_event_count,
        paper_sharpe=paper_sharpe,
        live_sharpe=live_sharpe,
    )


def build_gray_release_report_snapshot(
    session: Session,
    *,
    generated_at: datetime,
    evidence_window_started: bool,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    paper_sharpe: Decimal = Decimal("0.0000"),
    live_sharpe: Decimal = Decimal("0.0000"),
) -> GrayReleaseReportSnapshot:
    generated_at_utc = _as_utc(generated_at)
    report = build_persisted_parallel_run_report(
        session,
        start_at=start_at,
        end_at=end_at,
        paper_sharpe=paper_sharpe,
        live_sharpe=live_sharpe,
    )
    blockers: list[str] = []
    if not evidence_window_started:
        blockers.append("formal_evidence_window_not_started")
    if report.observation_count == 0:
        blockers.append("no_parallel_observations")
    if report.running_days < Decimal("14.0000"):
        blockers.append("parallel_runtime_less_than_14_days")
    if report.risk_event_count > 0:
        blockers.append("risk_events_present")
    if report.sharpe_deviation >= Decimal("0.2000"):
        blockers.append("sharpe_deviation_at_or_above_20_percent")
    if report.direction_divergence_count > 0:
        blockers.append("direction_divergence_present")

    acceptance_ready = evidence_window_started and report.can_promote_capital and not blockers
    return GrayReleaseReportSnapshot(
        generated_at=generated_at_utc,
        observation_count=report.observation_count,
        direction_divergence_count=report.direction_divergence_count,
        direction_divergence_rate=report.direction_divergence_rate,
        average_latency_delta_seconds=report.average_latency_delta_seconds,
        average_slippage_bps=report.average_slippage_bps,
        sharpe_deviation=report.sharpe_deviation,
        running_days=report.running_days,
        risk_event_count=report.risk_event_count,
        can_promote_capital=report.can_promote_capital,
        evidence_window_started=evidence_window_started,
        acceptance_ready=acceptance_ready,
        acceptance_blockers=blockers,
    )


def _parallel_running_days(observations: list[LiveParallelObservation]) -> Decimal:
    if not observations:
        return Decimal("0.0000")
    first_time = _as_utc(observations[0].signal_time)
    last_time = _as_utc(observations[-1].signal_time)
    elapsed_seconds = Decimal(str((last_time - first_time).total_seconds()))
    return _quantize_ratio(elapsed_seconds / Decimal("86400"))


def collect_parallel_run_observations(
    session: Session,
    *,
    broker: Any,
    as_of: datetime,
    total_equity: Decimal,
    daily_notional_so_far: Decimal = Decimal("0.00000000"),
    approval_actor: str = "phase5_observation_job",
) -> ParallelObservationCollectionResult:
    as_of_utc = _as_utc(as_of)
    existing_signal_ids = set(session.execute(select(LiveParallelObservation.signal_id)).scalars().all())
    orders = session.execute(
        select(PaperOrder)
        .options(selectinload(PaperOrder.signal))
        .where(
            PaperOrder.status == "filled",
            PaperOrder.price.is_not(None),
            PaperOrder.filled_at.is_not(None),
        )
        .order_by(PaperOrder.filled_at.asc(), PaperOrder.id.asc())
    ).scalars().all()

    observed_count = 0
    skipped_count = 0
    for order in orders:
        signal_id = str(order.signal_id)
        if signal_id in existing_signal_ids:
            skipped_count += 1
            continue
        if order.price is None or order.filled_at is None or order.signal is None:
            skipped_count += 1
            continue

        live_order_request = LiveOrderRequest(
            symbol=order.symbol,
            side=order.side,  # type: ignore[arg-type]
            quantity=order.quantity,
            price=order.price,
            confidence=order.signal.confidence,
            daily_notional_so_far=_quantize_money(daily_notional_so_far),
            total_equity=_quantize_money(total_equity),
        )
        live_config = load_live_readiness_config(
            {
                "live": {
                    "enabled": True,
                    "kill_switch_enabled": False,
                    "daily_notional_limit": "1000000000.00000000",
                    "max_initial_capital_fraction": "1.0000",
                    "real_broker_routing_enabled": True,
                }
            }
        )
        routing_request = LiveBrokerRoutingRequest(
            broker_name="ibkr",
            credentials_configured=bool(getattr(broker, "is_available", False)),
            manual_approval_id=f"phase5-observation-{order.id}",
            approval_actor=approval_actor,
            approved_at=as_of_utc,
        )
        dry_run = broker.dry_run_order_lifecycle(
            config=live_config,
            order_request=live_order_request,
            routing_request=routing_request,
            submitted_at=as_of_utc,
        )

        record_parallel_run_observation(
            session,
            signal_id=signal_id,
            symbol=order.symbol,
            signal_time=order.signal.signal_time,
            paper_direction=order.side,
            live_direction=dry_run.side if dry_run.accepted else "REJECTED",
            paper_order_time=order.filled_at,
            live_order_time=dry_run.submitted_at,
            paper_fill_price=order.price,
            live_fill_price=dry_run.price if dry_run.accepted else order.price,
            order_notional=dry_run.order_notional,
            dry_run_status=dry_run.status,
            guard_passed=dry_run.accepted,
            risk_event_count=_risk_events_for_order(session, order),
            observed_at=as_of_utc,
            metadata={
                "dry_run": True,
                "dry_run_lifecycle": dry_run.lifecycle,
                "manual_approval_id": routing_request.manual_approval_id,
                "approval_actor": routing_request.approval_actor,
            },
        )
        existing_signal_ids.add(signal_id)
        observed_count += 1

    return ParallelObservationCollectionResult(
        observed_count=observed_count,
        skipped_count=skipped_count,
        as_of=as_of_utc,
    )


def _risk_events_for_order(session: Session, order: PaperOrder) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(RiskEvent).where(RiskEvent.related_order_id == order.id)
        ).scalar_one()
    )
