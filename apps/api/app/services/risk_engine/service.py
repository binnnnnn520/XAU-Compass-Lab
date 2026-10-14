from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models import AuditLog, MarketBar, PaperPosition, RiskEvent, SentimentScore, Signal, StrategyRun
from app.schemas import PaginatedData, RiskEventData, RiskStatusData, RiskStatusEventSummary


MONEY_QUANTIZER = Decimal("0.00000001")
RATIO_QUANTIZER = Decimal("0.000001")
DISPLAY_QUANTIZER = Decimal("0.01")
DEFAULT_INITIAL_CAPITAL = Decimal("100000.00")
CANONICAL_SYMBOL = "XAUUSD"
CANONICAL_TIMEFRAME = "1h"


@dataclass(frozen=True)
class RiskConfig:
    initial_capital: Decimal = DEFAULT_INITIAL_CAPITAL
    default_order_quantity: Decimal = Decimal("1.00000000")
    max_drawdown_limit: Decimal = Decimal("-0.10")
    max_drawdown_warning: Decimal = Decimal("-0.07")
    max_open_positions: int = 3
    max_total_exposure: Decimal = Decimal("0.80")
    max_position_value: Decimal = Decimal("0.30")
    max_risk_per_trade: Decimal = Decimal("0.02")
    max_position_holding_hours: int | None = None
    max_position_loss_pct: Decimal | None = None
    max_same_direction_positions: int | None = None
    estimated_volatility: Decimal = Decimal("0.02")
    circuit_breaker_window: timedelta = timedelta(hours=1)
    circuit_breaker_threshold: Decimal = Decimal("-0.7")
    circuit_breaker_min_count: int = 5
    circuit_breaker_cooldown: timedelta = timedelta(hours=2)
    manual_approval_required: bool = False


@dataclass(frozen=True)
class AccountSnapshot:
    initial_capital: Decimal
    total_equity: Decimal
    cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_exposure: Decimal
    open_positions: int
    peak_equity: Decimal
    current_drawdown: Decimal


@dataclass(frozen=True)
class RiskEventPayload:
    event_type: str
    severity: str
    action_taken: str
    trigger_value: Decimal | None
    threshold_value: Decimal | None
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskDecision:
    passed: bool
    account_snapshot: AccountSnapshot
    config: RiskConfig
    checks_result: dict[str, Any]
    reject_reason: str | None = None
    event_payload: RiskEventPayload | None = None
    warning_events: tuple[RiskEventPayload, ...] = ()
    requires_manual_approval: bool = False


def _to_decimal(value: Any, *, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    return Decimal(str(value))


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def _quantize_ratio(value: Decimal) -> Decimal:
    return value.quantize(RATIO_QUANTIZER, rounding=ROUND_HALF_UP)


def _serialize_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def load_risk_config(parameters: dict[str, Any] | None) -> RiskConfig:
    raw_parameters = parameters or {}
    risk_parameters = raw_parameters.get("risk", {})
    paper_parameters = raw_parameters.get("paper", {})

    def decimal_value(container: dict[str, Any], key: str, default: Decimal) -> Decimal:
        return _to_decimal(container.get(key), default=default) or default

    def int_value(container: dict[str, Any], key: str, default: int) -> int:
        value = container.get(key)
        return default if value is None else int(value)

    def optional_int_value(container: dict[str, Any], key: str) -> int | None:
        value = container.get(key)
        return None if value is None else int(value)

    def optional_decimal_value(container: dict[str, Any], key: str) -> Decimal | None:
        value = container.get(key)
        if value is None:
            return None
        return _to_decimal(value)

    def bool_value(container: dict[str, Any], key: str, default: bool) -> bool:
        value = container.get(key)
        return default if value is None else bool(value)

    return RiskConfig(
        initial_capital=decimal_value(paper_parameters, "initial_capital", DEFAULT_INITIAL_CAPITAL).quantize(
            DISPLAY_QUANTIZER, rounding=ROUND_HALF_UP
        ),
        default_order_quantity=decimal_value(paper_parameters, "order_quantity", Decimal("1.00000000")).quantize(
            MONEY_QUANTIZER, rounding=ROUND_HALF_UP
        ),
        max_drawdown_limit=decimal_value(risk_parameters, "max_drawdown_limit", Decimal("-0.10")),
        max_drawdown_warning=decimal_value(risk_parameters, "max_drawdown_warning", Decimal("-0.07")),
        max_open_positions=int_value(risk_parameters, "max_open_positions", 3),
        max_total_exposure=decimal_value(risk_parameters, "max_total_exposure", Decimal("0.80")),
        max_position_value=decimal_value(risk_parameters, "max_position_value", Decimal("0.30")),
        max_risk_per_trade=decimal_value(risk_parameters, "max_risk_per_trade", Decimal("0.02")),
        max_position_holding_hours=optional_int_value(risk_parameters, "max_position_holding_hours"),
        max_position_loss_pct=optional_decimal_value(risk_parameters, "max_position_loss_pct"),
        max_same_direction_positions=optional_int_value(risk_parameters, "max_same_direction_positions"),
        estimated_volatility=decimal_value(risk_parameters, "estimated_volatility", Decimal("0.02")),
        circuit_breaker_window=timedelta(hours=int_value(risk_parameters, "circuit_breaker_window_hours", 1)),
        circuit_breaker_threshold=decimal_value(risk_parameters, "circuit_breaker_threshold", Decimal("-0.7")),
        circuit_breaker_min_count=int_value(risk_parameters, "circuit_breaker_min_count", 5),
        circuit_breaker_cooldown=timedelta(hours=int_value(risk_parameters, "circuit_breaker_cooldown_hours", 2)),
        manual_approval_required=bool_value(risk_parameters, "manual_approval_required", False),
    )


def _latest_market_price(session: Session, symbol: str, as_of: datetime) -> Decimal | None:
    return session.execute(
        select(MarketBar.close)
        .where(
            MarketBar.symbol == symbol,
            MarketBar.timeframe == CANONICAL_TIMEFRAME,
            MarketBar.bar_time <= as_of,
        )
        .order_by(MarketBar.bar_time.desc())
        .limit(1)
    ).scalar_one_or_none()


def _position_unrealized_pnl(position: PaperPosition, current_price: Decimal) -> Decimal:
    if position.side == "LONG":
        return _quantize_money((current_price - position.entry_price) * position.quantity)
    return _quantize_money((position.entry_price - current_price) * position.quantity)


def _position_market_value(position: PaperPosition, current_price: Decimal) -> Decimal:
    return _quantize_money(current_price * position.quantity)


def _peak_equity_from_audit_logs(session: Session, initial_capital: Decimal) -> Decimal:
    peak = initial_capital
    logs = session.execute(
        select(AuditLog).where(AuditLog.new_value.is_not(None)).order_by(AuditLog.created_at.asc())
    ).scalars().all()
    for log in logs:
        if not isinstance(log.new_value, dict):
            continue
        snapshot = log.new_value.get("account_snapshot")
        if not isinstance(snapshot, dict):
            continue
        total_equity = snapshot.get("total_equity")
        if total_equity is None:
            continue
        value = Decimal(str(total_equity))
        if value > peak:
            peak = value
    return peak


def build_account_snapshot(
    session: Session,
    *,
    as_of: datetime,
    config: RiskConfig,
) -> AccountSnapshot:
    open_positions = session.execute(
        select(PaperPosition)
        .where(PaperPosition.status == "open")
        .order_by(PaperPosition.opened_at.asc(), PaperPosition.id.asc())
    ).scalars().all()
    realized_total = session.execute(
        select(func.coalesce(func.sum(PaperPosition.realized_pnl), 0)).select_from(PaperPosition)
    ).scalar_one()
    realized_pnl = _quantize_money(Decimal(str(realized_total)))

    unrealized_pnl = Decimal("0")
    total_exposure = Decimal("0")
    for position in open_positions:
        current_price = _latest_market_price(session, position.symbol, as_of) or position.current_price or position.entry_price
        unrealized_pnl += _position_unrealized_pnl(position, current_price)
        total_exposure += _position_market_value(position, current_price)

    unrealized_pnl = _quantize_money(unrealized_pnl)
    total_exposure = _quantize_money(total_exposure)
    total_equity = _quantize_money(config.initial_capital + realized_pnl + unrealized_pnl)
    peak_equity = max(total_equity, _peak_equity_from_audit_logs(session, config.initial_capital), config.initial_capital)
    if peak_equity <= Decimal("0"):
        current_drawdown = Decimal("0")
    else:
        current_drawdown = _quantize_ratio((total_equity - peak_equity) / peak_equity)
    cash = _quantize_money(total_equity - total_exposure)
    return AccountSnapshot(
        initial_capital=config.initial_capital,
        total_equity=total_equity,
        cash=cash,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_exposure=total_exposure,
        open_positions=len(open_positions),
        peak_equity=peak_equity,
        current_drawdown=current_drawdown,
    )


def _active_circuit_breaker_event(session: Session, *, as_of: datetime, config: RiskConfig) -> RiskEvent | None:
    return session.execute(
        select(RiskEvent)
        .where(
            RiskEvent.event_type == "circuit_breaker",
            RiskEvent.created_at >= as_of - config.circuit_breaker_cooldown,
        )
        .order_by(RiskEvent.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _recent_sentiment_window(
    session: Session,
    *,
    as_of: datetime,
    config: RiskConfig,
) -> tuple[int, Decimal | None]:
    sentiment_count, average_score = session.execute(
        select(func.count(SentimentScore.id), func.avg(SentimentScore.score))
        .where(
            SentimentScore.created_at > as_of - config.circuit_breaker_window,
            SentimentScore.created_at <= as_of,
        )
    ).one()
    if average_score is None:
        return int(sentiment_count or 0), None
    return int(sentiment_count or 0), Decimal(str(average_score))


def _serialize_account_snapshot(snapshot: AccountSnapshot) -> dict[str, str | int]:
    return {
        "initial_capital": _serialize_decimal(snapshot.initial_capital) or "0",
        "total_equity": _serialize_decimal(snapshot.total_equity) or "0",
        "cash": _serialize_decimal(snapshot.cash) or "0",
        "realized_pnl": _serialize_decimal(snapshot.realized_pnl) or "0",
        "unrealized_pnl": _serialize_decimal(snapshot.unrealized_pnl) or "0",
        "total_exposure": _serialize_decimal(snapshot.total_exposure) or "0",
        "open_positions": snapshot.open_positions,
        "peak_equity": _serialize_decimal(snapshot.peak_equity) or "0",
        "current_drawdown": _serialize_decimal(snapshot.current_drawdown) or "0",
    }


def evaluate_signal_risk(
    session: Session,
    signal: Signal,
    *,
    quantity: Decimal,
    reference_price: Decimal,
) -> RiskDecision:
    config = load_risk_config(signal.strategy_run.parameters if signal.strategy_run is not None else {})
    account_snapshot = build_account_snapshot(session, as_of=signal.signal_time, config=config)
    opposite_side = "SHORT" if signal.direction == "BUY" else "LONG"
    offset_quantity_raw = session.execute(
        select(func.coalesce(func.sum(PaperPosition.quantity), 0))
        .where(
            PaperPosition.symbol == signal.symbol,
            PaperPosition.side == opposite_side,
            PaperPosition.status == "open",
        )
    ).scalar_one()
    offset_quantity = Decimal(str(offset_quantity_raw))
    net_new_quantity = max(Decimal("0"), _quantize_money(quantity - offset_quantity))
    new_order_value = _quantize_money(net_new_quantity * reference_price)
    checks_result: dict[str, Any] = {
        "risk_check_order": [
            "circuit_breaker",
            "max_drawdown",
            "open_position_count",
            "direction_concentration",
            "total_exposure",
            "per_trade_risk",
            "manual_approval_switch",
        ],
        "account_snapshot": _serialize_account_snapshot(account_snapshot),
        "offset_quantity": _serialize_decimal(offset_quantity),
        "net_new_quantity": _serialize_decimal(net_new_quantity),
        "new_order_value": _serialize_decimal(new_order_value),
    }
    warning_events: list[RiskEventPayload] = []

    if net_new_quantity == Decimal("0"):
        checks_result["close_only"] = True
        checks_result["manual_approval_switch"] = config.manual_approval_required
        return RiskDecision(
            passed=True,
            account_snapshot=account_snapshot,
            config=config,
            checks_result=checks_result,
            requires_manual_approval=config.manual_approval_required,
        )

    active_breaker = _active_circuit_breaker_event(session, as_of=signal.signal_time, config=config)
    if active_breaker is not None:
        checks_result["circuit_breaker"] = "active"
        return RiskDecision(
            passed=False,
            account_snapshot=account_snapshot,
            config=config,
            checks_result=checks_result,
            reject_reason="circuit_breaker_active",
            event_payload=RiskEventPayload(
                event_type="circuit_breaker",
                severity="critical",
                action_taken="reject_order",
                trigger_value=None,
                threshold_value=config.circuit_breaker_threshold,
                description="Circuit breaker cooldown is still active.",
                metadata={"source": "cooldown"},
            ),
        )

    sentiment_count, average_score = _recent_sentiment_window(session, as_of=signal.signal_time, config=config)
    checks_result["circuit_breaker"] = {
        "sentiment_count": sentiment_count,
        "average_score": _serialize_decimal(average_score),
    }
    if (
        average_score is not None
        and sentiment_count >= config.circuit_breaker_min_count
        and average_score <= config.circuit_breaker_threshold
    ):
        return RiskDecision(
            passed=False,
            account_snapshot=account_snapshot,
            config=config,
            checks_result=checks_result,
            reject_reason="circuit_breaker_active",
            event_payload=RiskEventPayload(
                event_type="circuit_breaker",
                severity="critical",
                action_taken="reject_order",
                trigger_value=average_score,
                threshold_value=config.circuit_breaker_threshold,
                description="Recent sentiment breached the circuit breaker threshold.",
                metadata={
                    "sentiment_count": sentiment_count,
                    "cooldown_hours": int(config.circuit_breaker_cooldown.total_seconds() // 3600),
                },
            ),
        )

    checks_result["max_drawdown"] = _serialize_decimal(account_snapshot.current_drawdown)
    if account_snapshot.current_drawdown <= config.max_drawdown_limit:
        return RiskDecision(
            passed=False,
            account_snapshot=account_snapshot,
            config=config,
            checks_result=checks_result,
            reject_reason="max_drawdown_breach",
            event_payload=RiskEventPayload(
                event_type="max_drawdown_breach",
                severity="critical",
                action_taken="reject_order",
                trigger_value=account_snapshot.current_drawdown,
                threshold_value=config.max_drawdown_limit,
                description="Current drawdown breached the configured hard limit.",
            ),
        )
    if account_snapshot.current_drawdown <= config.max_drawdown_warning:
        warning_events.append(
            RiskEventPayload(
                event_type="drawdown_warning",
                severity="warning",
                action_taken="alert_only",
                trigger_value=account_snapshot.current_drawdown,
                threshold_value=config.max_drawdown_warning,
                description="Current drawdown breached the warning threshold.",
            )
        )

    checks_result["open_position_count"] = account_snapshot.open_positions
    if account_snapshot.open_positions >= config.max_open_positions:
        return RiskDecision(
            passed=False,
            account_snapshot=account_snapshot,
            config=config,
            checks_result=checks_result,
            reject_reason="max_positions_reached",
            event_payload=RiskEventPayload(
                event_type="position_limit",
                severity="warning",
                action_taken="reject_order",
                trigger_value=Decimal(account_snapshot.open_positions),
                threshold_value=Decimal(config.max_open_positions),
                description="Open position count is already at the configured limit.",
            ),
        )

    same_side = "LONG" if signal.direction == "BUY" else "SHORT"
    same_direction_count = session.execute(
        select(func.count(PaperPosition.id)).where(
            PaperPosition.symbol == signal.symbol,
            PaperPosition.side == same_side,
            PaperPosition.status == "open",
        )
    ).scalar_one()
    checks_result["direction_concentration"] = {
        "side": same_side,
        "open_positions": int(same_direction_count),
        "limit": config.max_same_direction_positions,
    }
    if config.max_same_direction_positions is not None and same_direction_count >= config.max_same_direction_positions:
        return RiskDecision(
            passed=False,
            account_snapshot=account_snapshot,
            config=config,
            checks_result=checks_result,
            reject_reason="direction_concentration_exceeded",
            event_payload=RiskEventPayload(
                event_type="direction_concentration_exceeded",
                severity="warning",
                action_taken="reject_order",
                trigger_value=Decimal(int(same_direction_count)),
                threshold_value=Decimal(config.max_same_direction_positions),
                description="Same-direction open positions are already at the configured concentration limit.",
                metadata={"side": same_side},
            ),
        )

    exposure_limit = _quantize_money(account_snapshot.total_equity * config.max_total_exposure)
    checks_result["total_exposure"] = {
        "current_exposure": _serialize_decimal(account_snapshot.total_exposure),
        "limit": _serialize_decimal(exposure_limit),
    }
    if account_snapshot.total_exposure + new_order_value > exposure_limit:
        return RiskDecision(
            passed=False,
            account_snapshot=account_snapshot,
            config=config,
            checks_result=checks_result,
            reject_reason="total_exposure_exceeded",
            event_payload=RiskEventPayload(
                event_type="total_exposure_exceeded",
                severity="warning",
                action_taken="reject_order",
                trigger_value=account_snapshot.total_exposure + new_order_value,
                threshold_value=exposure_limit,
                description="Total exposure would exceed the configured account limit.",
            ),
        )

    max_position_value = _quantize_money(account_snapshot.total_equity * config.max_position_value)
    estimated_risk = _quantize_money(new_order_value * config.estimated_volatility)
    max_trade_risk = _quantize_money(account_snapshot.total_equity * config.max_risk_per_trade)
    checks_result["per_trade_risk"] = {
        "position_value_limit": _serialize_decimal(max_position_value),
        "estimated_risk": _serialize_decimal(estimated_risk),
        "risk_limit": _serialize_decimal(max_trade_risk),
    }
    if new_order_value > max_position_value:
        return RiskDecision(
            passed=False,
            account_snapshot=account_snapshot,
            config=config,
            checks_result=checks_result,
            reject_reason="position_value_exceeded",
            event_payload=RiskEventPayload(
                event_type="position_value_exceeded",
                severity="warning",
                action_taken="reject_order",
                trigger_value=new_order_value,
                threshold_value=max_position_value,
                description="Order notional would exceed the per-trade position value limit.",
            ),
        )
    if estimated_risk > max_trade_risk:
        return RiskDecision(
            passed=False,
            account_snapshot=account_snapshot,
            config=config,
            checks_result=checks_result,
            reject_reason="risk_per_trade_exceeded",
            event_payload=RiskEventPayload(
                event_type="risk_per_trade_exceeded",
                severity="warning",
                action_taken="reject_order",
                trigger_value=estimated_risk,
                threshold_value=max_trade_risk,
                description="Estimated trade risk would exceed the configured risk-per-trade limit.",
            ),
        )

    checks_result["manual_approval_switch"] = config.manual_approval_required
    return RiskDecision(
        passed=True,
        account_snapshot=account_snapshot,
        config=config,
        checks_result=checks_result,
        warning_events=tuple(warning_events),
        requires_manual_approval=config.manual_approval_required,
    )


def _serialize_risk_event(event: RiskEvent) -> RiskEventData:
    return RiskEventData(
        id=event.id,
        event_type=event.event_type,
        severity=event.severity,
        trigger_value=event.trigger_value,
        threshold_value=event.threshold_value,
        action_taken=event.action_taken,
        related_order_id=event.related_order_id,
        description=event.description,
        metadata=event.metadata_json,
        created_at=event.created_at,
    )


def list_risk_events(
    session: Session,
    *,
    page: int,
    page_size: int,
    severity: str | None,
    event_type: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
) -> PaginatedData[RiskEventData]:
    row_query = select(RiskEvent.id).select_from(RiskEvent)
    if severity is not None:
        row_query = row_query.where(RiskEvent.severity == severity)
    if event_type is not None:
        row_query = row_query.where(RiskEvent.event_type == event_type)
    if start_date is not None:
        row_query = row_query.where(RiskEvent.created_at >= start_date)
    if end_date is not None:
        row_query = row_query.where(RiskEvent.created_at <= end_date)

    total = session.execute(select(func.count()).select_from(row_query.subquery())).scalar_one()
    ids = session.execute(
        row_query.order_by(RiskEvent.created_at.desc(), RiskEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    if not ids:
        return PaginatedData[RiskEventData](items=[], total=total, page=page, page_size=page_size)

    events = session.execute(select(RiskEvent).where(RiskEvent.id.in_(ids))).scalars().all()
    by_id = {event.id: event for event in events}
    return PaginatedData[RiskEventData](
        items=[_serialize_risk_event(by_id[event_id]) for event_id in ids],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_risk_status(session: Session) -> RiskStatusData:
    strategy = session.execute(
        select(StrategyRun).where(StrategyRun.is_active.is_(True)).order_by(StrategyRun.updated_at.desc())
    ).scalar_one_or_none()
    config = load_risk_config(strategy.parameters if strategy is not None else {})
    as_of = utcnow()
    account_snapshot = build_account_snapshot(session, as_of=as_of, config=config)
    circuit_breaker_active = _active_circuit_breaker_event(session, as_of=as_of, config=config) is not None
    if not circuit_breaker_active:
        sentiment_count, average_score = _recent_sentiment_window(session, as_of=as_of, config=config)
        circuit_breaker_active = (
            average_score is not None
            and sentiment_count >= config.circuit_breaker_min_count
            and average_score <= config.circuit_breaker_threshold
        )

    last_event = session.execute(select(RiskEvent).order_by(RiskEvent.created_at.desc()).limit(1)).scalar_one_or_none()
    return RiskStatusData(
        trading_enabled=not circuit_breaker_active and account_snapshot.current_drawdown > config.max_drawdown_limit,
        current_drawdown=account_snapshot.current_drawdown,
        max_drawdown_limit=config.max_drawdown_limit,
        position_count=account_snapshot.open_positions,
        position_limit=config.max_open_positions,
        circuit_breaker_active=circuit_breaker_active,
        last_risk_event=(
            None
            if last_event is None
            else RiskStatusEventSummary(type=last_event.event_type, time=last_event.created_at.astimezone(UTC))
        ),
    )
