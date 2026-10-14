from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditLog, PaperOrder, PaperPosition, Signal, StrategyRun
from app.schemas import ApiException, PaginatedData, PaperAccountData, PaperOrderData, PaperPositionData
from app.services.risk_engine import (
    RiskEventPayload,
    build_account_snapshot,
    evaluate_signal_risk,
    load_risk_config,
)
from app.services.risk_engine.service import _latest_market_price


MONEY_QUANTIZER = Decimal("0.00000001")
DISPLAY_QUANTIZER = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def _paper_decimal_parameter(parameters: dict[str, Any], key: str) -> Decimal | None:
    value = parameters.get(key)
    if value is None:
        return None
    decimal_value = Decimal(str(value))
    if decimal_value <= Decimal("0"):
        return None
    return _quantize_money(decimal_value)


def _initial_trailing_stop_price(direction: str, fill_price: Decimal, distance: Decimal | None) -> Decimal | None:
    if distance is None:
        return None
    if direction == "BUY":
        return _quantize_money(fill_price - distance)
    return _quantize_money(fill_price + distance)


def _configured_stops(
    *,
    direction: str,
    fill_price: Decimal,
    parameters: dict[str, Any] | None,
) -> dict[str, Decimal | None]:
    raw_parameters = parameters or {}
    paper_parameters = raw_parameters.get("paper", {}) if isinstance(raw_parameters, dict) else {}
    if not isinstance(paper_parameters, dict):
        paper_parameters = {}

    stop_loss_distance = _paper_decimal_parameter(paper_parameters, "stop_loss_distance")
    take_profit_distance = _paper_decimal_parameter(paper_parameters, "take_profit_distance")
    trailing_stop_distance = _paper_decimal_parameter(paper_parameters, "trailing_stop_distance")

    if direction == "BUY":
        stop_loss = _quantize_money(fill_price - stop_loss_distance) if stop_loss_distance is not None else None
        take_profit = _quantize_money(fill_price + take_profit_distance) if take_profit_distance is not None else None
    else:
        stop_loss = _quantize_money(fill_price + stop_loss_distance) if stop_loss_distance is not None else None
        take_profit = _quantize_money(fill_price - take_profit_distance) if take_profit_distance is not None else None

    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "trailing_stop_distance": trailing_stop_distance,
        "trailing_stop_price": _initial_trailing_stop_price(direction, fill_price, trailing_stop_distance),
    }


def _serialize_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {key: _serialize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_json(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize_json(item) for item in value]
    return value


def _serialize_order(order: PaperOrder) -> PaperOrderData:
    return PaperOrderData(
        id=order.id,
        signal_id=order.signal_id,
        symbol=order.symbol,
        side=order.side,
        order_type=order.order_type,
        quantity=order.quantity,
        price=order.price,
        limit_price=order.limit_price,
        stop_loss=order.stop_loss,
        take_profit=order.take_profit,
        slippage=order.slippage,
        commission=order.commission,
        status=order.status,
        reject_reason=order.reject_reason,
        filled_at=order.filled_at,
        created_at=order.created_at,
    )


def _position_state(position: PaperPosition, session: Session, as_of: datetime) -> dict[str, Any]:
    current_price = _latest_market_price(session, position.symbol, as_of) or position.current_price or position.entry_price
    if position.side == "LONG":
        unrealized = _quantize_money((current_price - position.entry_price) * position.quantity)
    else:
        unrealized = _quantize_money((position.entry_price - current_price) * position.quantity)
    return {
        "current_price": current_price,
        "unrealized_pnl": unrealized,
    }


def _serialize_position(position: PaperPosition, session: Session, as_of: datetime) -> PaperPositionData:
    state = _position_state(position, session, as_of)
    return PaperPositionData(
        id=position.id,
        symbol=position.symbol,
        side=position.side,
        quantity=position.quantity,
        entry_price=position.entry_price,
        current_price=state["current_price"],
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        trailing_stop_distance=position.trailing_stop_distance,
        trailing_stop_price=position.trailing_stop_price,
        unrealized_pnl=state["unrealized_pnl"],
        realized_pnl=position.realized_pnl,
        status=position.status,
        opened_at=position.opened_at,
        closed_at=position.closed_at,
        entry_order_id=position.entry_order_id,
        exit_order_id=position.exit_order_id,
        created_at=position.created_at,
        updated_at=position.updated_at,
    )


def _create_audit_log(
    session: Session,
    *,
    action: str,
    entity_type: str | None,
    entity_id: UUID | None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor="system",
        old_value=_serialize_json(old_value) if old_value is not None else None,
        new_value=_serialize_json(new_value) if new_value is not None else None,
    )
    session.add(log)
    session.flush()
    return log


def _create_risk_event(
    session: Session,
    *,
    order: PaperOrder,
    payload: RiskEventPayload,
) -> None:
    from app.models import RiskEvent

    session.add(
        RiskEvent(
            event_type=payload.event_type,
            severity=payload.severity,
            trigger_value=payload.trigger_value,
            threshold_value=payload.threshold_value,
            action_taken=payload.action_taken,
            related_order_id=order.id,
            description=payload.description,
            metadata_json=_serialize_json(payload.metadata),
        )
    )
    session.flush()


def _load_signal(session: Session, signal_id: UUID) -> Signal:
    signal = session.execute(
        select(Signal)
        .options(selectinload(Signal.strategy_run))
        .where(Signal.id == signal_id)
    ).scalar_one_or_none()
    if signal is None:
        raise ApiException(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="Signal not found.",
            detail={"signal_id": str(signal_id)},
        )
    if signal.direction not in {"BUY", "SELL"}:
        raise ApiException(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message="Only BUY or SELL signals can be sent to paper execution.",
            detail={"signal_id": str(signal_id), "direction": signal.direction},
        )
    return signal


def _fill_price(signal: Signal, session: Session) -> Decimal:
    price = signal.price_at_signal or _latest_market_price(session, signal.symbol, signal.signal_time)
    if price is None:
        raise ApiException(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message="Paper execution requires a reference market price.",
            detail={"signal_id": str(signal.id)},
        )
    return _quantize_money(price)


def _snapshot_payload(session: Session, *, as_of: datetime, config) -> dict[str, Any]:
    snapshot = build_account_snapshot(session, as_of=as_of, config=config)
    return {
        "account_snapshot": {
            "total_equity": format(snapshot.total_equity, "f"),
            "cash": format(snapshot.cash, "f"),
            "realized_pnl": format(snapshot.realized_pnl, "f"),
            "unrealized_pnl": format(snapshot.unrealized_pnl, "f"),
            "total_exposure": format(snapshot.total_exposure, "f"),
            "open_positions": snapshot.open_positions,
            "current_drawdown": format(snapshot.current_drawdown, "f"),
        }
    }


def _position_payload(position: PaperPosition, session: Session, as_of: datetime) -> dict[str, Any]:
    serialized = _serialize_position(position, session, as_of)
    return serialized.model_dump(mode="json")


def _apply_fill(
    session: Session,
    *,
    order: PaperOrder,
    fill_time: datetime,
    trailing_stop_distance: Decimal | None = None,
    trailing_stop_price: Decimal | None = None,
) -> None:
    fill_price = order.price or Decimal("0")
    opposite_side = "SHORT" if order.side == "BUY" else "LONG"
    same_side = "LONG" if order.side == "BUY" else "SHORT"
    remaining_quantity = order.quantity

    open_positions = session.execute(
        select(PaperPosition)
        .where(PaperPosition.symbol == order.symbol, PaperPosition.status == "open")
        .order_by(PaperPosition.opened_at.asc(), PaperPosition.id.asc())
    ).scalars().all()

    for position in open_positions:
        if remaining_quantity <= Decimal("0") or position.side != opposite_side:
            continue

        old_state = _position_payload(position, session, fill_time)
        closing_quantity = min(position.quantity, remaining_quantity)
        if position.side == "LONG":
            realized_delta = _quantize_money((fill_price - position.entry_price) * closing_quantity)
        else:
            realized_delta = _quantize_money((position.entry_price - fill_price) * closing_quantity)

        if closing_quantity == position.quantity:
            position.current_price = fill_price
            position.unrealized_pnl = Decimal("0")
            position.realized_pnl = _quantize_money(position.realized_pnl + realized_delta)
            position.status = "closed"
            position.closed_at = fill_time
            position.exit_order_id = order.id
        else:
            position.quantity = _quantize_money(position.quantity - closing_quantity)
            position.current_price = fill_price
            position.realized_pnl = _quantize_money(position.realized_pnl + realized_delta)
            position.unrealized_pnl = Decimal("0")

        session.add(position)
        session.flush()
        _create_audit_log(
            session,
            action="position_changed",
            entity_type="position",
            entity_id=position.id,
            old_value=old_state,
            new_value=_position_payload(position, session, fill_time),
        )
        remaining_quantity = _quantize_money(remaining_quantity - closing_quantity)

    if remaining_quantity <= Decimal("0"):
        return

    position = session.execute(
        select(PaperPosition)
        .where(
            PaperPosition.symbol == order.symbol,
            PaperPosition.side == same_side,
            PaperPosition.status == "open",
        )
        .order_by(PaperPosition.opened_at.asc())
        .limit(1)
    ).scalar_one_or_none()

    if position is None:
        position = PaperPosition(
            symbol=order.symbol,
            side=same_side,
            quantity=remaining_quantity,
            entry_price=fill_price,
            current_price=fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            trailing_stop_distance=trailing_stop_distance,
            trailing_stop_price=trailing_stop_price,
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            status="open",
            opened_at=fill_time,
            entry_order_id=order.id,
        )
        session.add(position)
        session.flush()
        _create_audit_log(
            session,
            action="position_changed",
            entity_type="position",
            entity_id=position.id,
            old_value=None,
            new_value=_position_payload(position, session, fill_time),
        )
        return

    old_state = _position_payload(position, session, fill_time)
    new_quantity = _quantize_money(position.quantity + remaining_quantity)
    weighted_entry = _quantize_money(
        ((position.entry_price * position.quantity) + (fill_price * remaining_quantity)) / new_quantity
    )
    position.quantity = new_quantity
    position.entry_price = weighted_entry
    position.current_price = fill_price
    if order.stop_loss is not None:
        position.stop_loss = order.stop_loss
    if order.take_profit is not None:
        position.take_profit = order.take_profit
    if trailing_stop_distance is not None:
        position.trailing_stop_distance = trailing_stop_distance
        position.trailing_stop_price = trailing_stop_price
    position.unrealized_pnl = Decimal("0")
    session.add(position)
    session.flush()
    _create_audit_log(
        session,
        action="position_changed",
        entity_type="position",
        entity_id=position.id,
        old_value=old_state,
        new_value=_position_payload(position, session, fill_time),
    )


def execute_signal(session: Session, signal_id: UUID) -> PaperOrder:
    signal = _load_signal(session, signal_id)
    strategy_parameters = signal.strategy_run.parameters if signal.strategy_run is not None else {}
    config = load_risk_config(strategy_parameters)
    fill_price = _fill_price(signal, session)
    stop_config = _configured_stops(direction=signal.direction, fill_price=fill_price, parameters=strategy_parameters)
    order = PaperOrder(
        signal_id=signal.id,
        symbol=signal.symbol,
        side=signal.direction,
        quantity=config.default_order_quantity,
        price=fill_price,
        stop_loss=stop_config["stop_loss"],
        take_profit=stop_config["take_profit"],
        order_type="MARKET",
        status="pending",
    )
    session.add(order)
    session.flush()

    _create_audit_log(
        session,
        action="signal_generated",
        entity_type="signal",
        entity_id=signal.id,
        new_value={
            "signal_id": signal.id,
            "direction": signal.direction,
            "features": signal.features_used,
        },
    )
    _create_audit_log(
        session,
        action="order_created",
        entity_type="order",
        entity_id=order.id,
        new_value={
            "order_id": order.id,
            "signal_id": signal.id,
            "quantity": order.quantity,
            "price": order.price,
            "stop_loss": order.stop_loss,
            "take_profit": order.take_profit,
            "trailing_stop_distance": stop_config["trailing_stop_distance"],
        },
    )

    try:
        decision = evaluate_signal_risk(session, signal, quantity=order.quantity, reference_price=fill_price)
    except Exception as exc:
        order.status = "rejected"
        order.reject_reason = "risk_evaluation_failed"
        session.add(order)
        session.flush()
        _create_risk_event(
            session,
            order=order,
            payload=RiskEventPayload(
                event_type="risk_evaluation_failed",
                severity="critical",
                action_taken="reject_order",
                trigger_value=None,
                threshold_value=None,
                description="Risk evaluation failed and the order was rejected by fail-safe policy.",
                metadata={"error": str(exc)},
            ),
        )
        _create_audit_log(
            session,
            action="risk_rejected",
            entity_type="order",
            entity_id=order.id,
            new_value={"order_id": order.id, "reject_reason": order.reject_reason},
        )
        return order

    for warning_event in decision.warning_events:
        _create_risk_event(session, order=order, payload=warning_event)

    if not decision.passed:
        order.status = "rejected"
        order.reject_reason = decision.reject_reason
        session.add(order)
        session.flush()
        if decision.event_payload is not None:
            _create_risk_event(session, order=order, payload=decision.event_payload)
        _create_audit_log(
            session,
            action="risk_rejected",
            entity_type="order",
            entity_id=order.id,
            new_value={
                "order_id": order.id,
                "reject_reason": decision.reject_reason,
                "checks_result": decision.checks_result,
            },
        )
        return order

    _create_audit_log(
        session,
        action="risk_passed",
        entity_type="order",
        entity_id=order.id,
        new_value={
            "order_id": order.id,
            "checks_result": decision.checks_result,
        },
    )

    if decision.requires_manual_approval:
        order.status = "pending_approval"
        session.add(order)
        session.flush()
        return order

    order.status = "filled"
    order.filled_at = signal.signal_time
    order.commission = Decimal("0")
    order.slippage = Decimal("0")
    session.add(order)
    session.flush()

    _apply_fill(
        session,
        order=order,
        fill_time=signal.signal_time,
        trailing_stop_distance=stop_config["trailing_stop_distance"],
        trailing_stop_price=stop_config["trailing_stop_price"],
    )
    _create_audit_log(
        session,
        action="order_filled",
        entity_type="order",
        entity_id=order.id,
        new_value={
            "order_id": order.id,
            "fill_price": order.price,
            **_snapshot_payload(session, as_of=signal.signal_time, config=config),
        },
    )
    return order


ACTIONABLE_SIGNAL_DIRECTIONS: tuple[str, ...] = ("BUY", "SELL")


def execute_pending_signals(session: Session, *, limit: int = 200) -> dict[str, int]:
    """Execute actionable signals that do not yet have a paper order.

    Bridges signal generation to paper execution so the live paper-trading loop
    produces filled orders for gray-release parallel observation. Each candidate
    signal is routed through ``execute_signal``, which enforces the fixed
    six-layer risk checks; non-actionable ``HOLD`` signals are never executed.
    Idempotent: signals that already have a paper order are skipped, so repeated
    runs only execute newly generated signals.
    """
    pending_signal_ids = session.execute(
        select(Signal.id)
        .outerjoin(PaperOrder, PaperOrder.signal_id == Signal.id)
        .where(PaperOrder.id.is_(None))
        .where(Signal.direction.in_(ACTIONABLE_SIGNAL_DIRECTIONS))
        .order_by(Signal.signal_time.asc(), Signal.id.asc())
        .limit(limit)
    ).scalars().all()

    counters = {
        "candidates": len(pending_signal_ids),
        "filled": 0,
        "rejected": 0,
        "pending_approval": 0,
    }
    for signal_id in pending_signal_ids:
        order = execute_signal(session, signal_id)
        if order.status == "filled":
            counters["filled"] += 1
        elif order.status == "rejected":
            counters["rejected"] += 1
        elif order.status == "pending_approval":
            counters["pending_approval"] += 1
    return counters


def list_paper_orders(
    session: Session,
    *,
    page: int,
    page_size: int,
    status_value: str | None,
) -> PaginatedData[PaperOrderData]:
    row_query = select(PaperOrder.id).select_from(PaperOrder)
    if status_value is not None:
        row_query = row_query.where(PaperOrder.status == status_value)
    total = session.execute(select(func.count()).select_from(row_query.subquery())).scalar_one()
    ids = session.execute(
        row_query.order_by(PaperOrder.created_at.desc(), PaperOrder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    if not ids:
        return PaginatedData[PaperOrderData](items=[], total=total, page=page, page_size=page_size)

    orders = session.execute(select(PaperOrder).where(PaperOrder.id.in_(ids))).scalars().all()
    by_id = {order.id: order for order in orders}
    return PaginatedData[PaperOrderData](
        items=[_serialize_order(by_id[order_id]) for order_id in ids],
        total=total,
        page=page,
        page_size=page_size,
    )


def list_paper_positions(
    session: Session,
    *,
    page: int,
    page_size: int,
    status_value: str | None,
) -> PaginatedData[PaperPositionData]:
    row_query = select(PaperPosition.id).select_from(PaperPosition)
    if status_value is not None:
        row_query = row_query.where(PaperPosition.status == status_value)
    total = session.execute(select(func.count()).select_from(row_query.subquery())).scalar_one()
    ids = session.execute(
        row_query.order_by(PaperPosition.opened_at.desc(), PaperPosition.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    if not ids:
        return PaginatedData[PaperPositionData](items=[], total=total, page=page, page_size=page_size)

    positions = session.execute(select(PaperPosition).where(PaperPosition.id.in_(ids))).scalars().all()
    by_id = {position.id: position for position in positions}
    as_of = datetime.now(UTC)
    return PaginatedData[PaperPositionData](
        items=[_serialize_position(by_id[position_id], session, as_of) for position_id in ids],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_paper_account(session: Session) -> PaperAccountData:
    strategy = session.execute(
        select(StrategyRun).where(StrategyRun.is_active.is_(True)).order_by(StrategyRun.updated_at.desc())
    ).scalar_one_or_none()
    config = load_risk_config(strategy.parameters if strategy is not None else {})
    snapshot = build_account_snapshot(session, as_of=datetime.now(UTC), config=config)
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today_realized = session.execute(
        select(func.coalesce(func.sum(PaperPosition.realized_pnl), 0))
        .where(PaperPosition.closed_at.is_not(None), PaperPosition.closed_at >= today_start)
    ).scalar_one()
    return PaperAccountData(
        total_equity=snapshot.total_equity.quantize(DISPLAY_QUANTIZER, rounding=ROUND_HALF_UP),
        cash=snapshot.cash.quantize(DISPLAY_QUANTIZER, rounding=ROUND_HALF_UP),
        unrealized_pnl=snapshot.unrealized_pnl.quantize(DISPLAY_QUANTIZER, rounding=ROUND_HALF_UP),
        realized_pnl=snapshot.realized_pnl.quantize(DISPLAY_QUANTIZER, rounding=ROUND_HALF_UP),
        open_positions=snapshot.open_positions,
        today_pnl=Decimal(str(today_realized)).quantize(DISPLAY_QUANTIZER, rounding=ROUND_HALF_UP),
    )
