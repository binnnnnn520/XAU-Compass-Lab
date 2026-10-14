from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import PaperOrder, PaperPosition, RiskEvent, StrategyRun
from app.services.paper_execution.service import (
    _create_audit_log,
    _position_payload,
    _quantize_money,
    _serialize_json,
)
from app.services.risk_engine.service import RiskConfig, _latest_market_price, _quantize_ratio, load_risk_config


PositionTrigger = Literal["stop_loss", "take_profit", "trailing_stop", "max_holding_time", "max_position_loss"]


def _active_risk_config(session: Session) -> RiskConfig:
    strategy = session.execute(
        select(StrategyRun).where(StrategyRun.is_active.is_(True)).order_by(StrategyRun.updated_at.desc()).limit(1)
    ).scalar_one_or_none()
    return load_risk_config(strategy.parameters if strategy is not None else {})


def _normalize_as_of(as_of: datetime | None) -> datetime:
    if as_of is None:
        return datetime.now(UTC)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Position stop checks require a UTC-aware as_of datetime.")
    return as_of.astimezone(UTC)


def _position_unrealized(position: PaperPosition, current_price: Decimal) -> Decimal:
    if position.side == "LONG":
        return _quantize_money((current_price - position.entry_price) * position.quantity)
    return _quantize_money((position.entry_price - current_price) * position.quantity)


def _position_notional(position: PaperPosition) -> Decimal:
    return _quantize_money(position.entry_price * position.quantity)


def _position_loss_ratio(position: PaperPosition, current_price: Decimal) -> Decimal:
    notional = _position_notional(position)
    if notional == Decimal("0"):
        return Decimal("0.000000")
    return _quantize_ratio(_position_unrealized(position, current_price) / notional)


def _stop_trigger_for(position: PaperPosition, current_price: Decimal) -> PositionTrigger | None:
    if position.side == "LONG":
        if position.stop_loss is not None and current_price <= position.stop_loss:
            return "stop_loss"
        if position.take_profit is not None and current_price >= position.take_profit:
            return "take_profit"
        if position.trailing_stop_price is not None and current_price <= position.trailing_stop_price:
            return "trailing_stop"
        return None

    if position.stop_loss is not None and current_price >= position.stop_loss:
        return "stop_loss"
    if position.take_profit is not None and current_price <= position.take_profit:
        return "take_profit"
    if position.trailing_stop_price is not None and current_price >= position.trailing_stop_price:
        return "trailing_stop"
    return None


def _risk_trigger_for(
    position: PaperPosition,
    *,
    current_price: Decimal,
    as_of: datetime,
    config: RiskConfig,
) -> tuple[PositionTrigger, Decimal | None, Decimal | None] | None:
    if config.max_position_holding_hours is not None:
        holding_time = as_of - position.opened_at.astimezone(UTC)
        holding_hours = Decimal(str(holding_time.total_seconds())) / Decimal("3600")
        if holding_hours >= Decimal(config.max_position_holding_hours):
            return (
                "max_holding_time",
                _quantize_ratio(holding_hours),
                Decimal(config.max_position_holding_hours),
            )

    if config.max_position_loss_pct is not None:
        loss_ratio = _position_loss_ratio(position, current_price)
        loss_limit = -config.max_position_loss_pct
        if loss_ratio <= loss_limit:
            return ("max_position_loss", loss_ratio, loss_limit)

    return None


def _update_trailing_stop(position: PaperPosition, current_price: Decimal) -> bool:
    if position.trailing_stop_distance is None:
        return False

    if position.side == "LONG":
        candidate = _quantize_money(current_price - position.trailing_stop_distance)
        if position.trailing_stop_price is None or candidate > position.trailing_stop_price:
            position.trailing_stop_price = candidate
            return True
        return False

    candidate = _quantize_money(current_price + position.trailing_stop_distance)
    if position.trailing_stop_price is None or candidate < position.trailing_stop_price:
        position.trailing_stop_price = candidate
        return True
    return False


def _close_position(
    session: Session,
    *,
    position: PaperPosition,
    current_price: Decimal,
    as_of: datetime,
    trigger: PositionTrigger,
    event_trigger_value: Decimal | None = None,
    event_threshold_value: Decimal | None = None,
) -> None:
    entry_order = position.entry_order
    if entry_order is None:
        return

    old_state = _position_payload(position, session, as_of)
    exit_order = PaperOrder(
        signal_id=entry_order.signal_id,
        symbol=position.symbol,
        side="SELL" if position.side == "LONG" else "BUY",
        order_type="MARKET",
        quantity=position.quantity,
        price=current_price,
        status="filled",
        filled_at=as_of,
    )
    session.add(exit_order)
    session.flush()

    realized_delta = _position_unrealized(position, current_price)
    position.current_price = current_price
    position.unrealized_pnl = Decimal("0")
    position.realized_pnl = _quantize_money(position.realized_pnl + realized_delta)
    position.status = "closed"
    position.closed_at = as_of
    position.exit_order_id = exit_order.id
    session.add(position)
    session.flush()

    event_type = f"{trigger}_triggered"
    threshold = (
        event_threshold_value
        if event_threshold_value is not None
        else getattr(position, trigger if trigger != "trailing_stop" else "trailing_stop_price")
    )
    session.add(
        RiskEvent(
            event_type=event_type,
            severity="warning",
            trigger_value=event_trigger_value if event_trigger_value is not None else current_price,
            threshold_value=threshold,
            action_taken="close_position",
            related_order_id=exit_order.id,
            description=f"Paper position closed after {trigger} was triggered.",
            metadata_json=_serialize_json(
                {
                    "position_id": position.id,
                    "entry_order_id": entry_order.id,
                    "exit_order_id": exit_order.id,
                    "side": position.side,
                }
            ),
        )
    )
    session.flush()

    _create_audit_log(
        session,
        action="position_stop_triggered",
        entity_type="position",
        entity_id=position.id,
        old_value=old_state,
        new_value=_position_payload(position, session, as_of),
    )


def check_open_position_stops(session: Session, *, as_of: datetime | None = None) -> int:
    check_time = _normalize_as_of(as_of)
    config = _active_risk_config(session)
    positions = session.execute(
        select(PaperPosition)
        .options(selectinload(PaperPosition.entry_order))
        .where(PaperPosition.status == "open")
        .order_by(PaperPosition.opened_at.asc(), PaperPosition.id.asc())
    ).scalars().all()

    closed_count = 0
    for position in positions:
        current_price = _latest_market_price(session, position.symbol, check_time) or position.current_price
        if current_price is None:
            continue
        current_price = _quantize_money(current_price)

        trigger = _stop_trigger_for(position, current_price)
        if trigger is not None:
            _close_position(session, position=position, current_price=current_price, as_of=check_time, trigger=trigger)
            closed_count += 1
            continue

        risk_trigger = _risk_trigger_for(position, current_price=current_price, as_of=check_time, config=config)
        if risk_trigger is not None:
            trigger, trigger_value, threshold_value = risk_trigger
            _close_position(
                session,
                position=position,
                current_price=current_price,
                as_of=check_time,
                trigger=trigger,
                event_trigger_value=trigger_value,
                event_threshold_value=threshold_value,
            )
            closed_count += 1
            continue

        old_trailing_stop_price = position.trailing_stop_price
        position.current_price = current_price
        position.unrealized_pnl = _position_unrealized(position, current_price)
        if _update_trailing_stop(position, current_price) or position.trailing_stop_price != old_trailing_stop_price:
            session.add(position)
            session.flush()

    return closed_count
