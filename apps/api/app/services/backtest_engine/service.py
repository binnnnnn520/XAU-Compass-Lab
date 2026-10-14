from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext
import math
from typing import Literal
from uuid import UUID

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import utcnow
from app.models import BacktestRun, MarketBar, StrategyRun
from app.schemas import (
    ApiException,
    BacktestCreateRequest,
    BacktestCreateResponseData,
    BacktestDetailData,
    BacktestListItemData,
    BacktestTradeLogItemData,
    PaginatedData,
)
from app.services.feature_engine import compute_features
from app.services.signal_engine import generate_signal


getcontext().prec = 28

DISPLAY_QUANTIZER = Decimal("0.01")
METRIC_QUANTIZER = Decimal("0.000001")
RATE_QUANTIZER = Decimal("0.0001")
BPS_DIVISOR = Decimal("10000")
CANONICAL_SYMBOL = "XAUUSD"
CANONICAL_TIMEFRAME = "1h"

BacktestStatus = Literal["pending", "running", "completed", "failed"]


@dataclass(frozen=True)
class PositionState:
    side: Literal["LONG", "SHORT"]
    quantity: Decimal
    entry_price: Decimal
    entry_time: datetime
    equity_after_entry_commission: Decimal
    entry_commission: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None


class BacktestDataInsufficientError(Exception):
    def __init__(self, message: str, detail: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(DISPLAY_QUANTIZER, rounding=ROUND_HALF_UP)


def _quantize_metric(value: Decimal) -> Decimal:
    return value.quantize(METRIC_QUANTIZER, rounding=ROUND_HALF_UP)


def _quantize_rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANTIZER, rounding=ROUND_HALF_UP)


def _execution_price(reference_price: Decimal, *, action: Literal["BUY", "SELL"], slippage_rate: Decimal) -> Decimal:
    multiplier = Decimal("1") + slippage_rate if action == "BUY" else Decimal("1") - slippage_rate
    return (reference_price * multiplier).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _commission(amount: Decimal, commission_rate: Decimal) -> Decimal:
    return (amount * commission_rate).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _current_equity(base_equity: Decimal, position: PositionState | None, current_price: Decimal, commission_rate: Decimal) -> Decimal:
    if position is None:
        return base_equity
    if position.side == "LONG":
        gross_pnl = (current_price - position.entry_price) * position.quantity
    else:
        gross_pnl = (position.entry_price - current_price) * position.quantity
    exit_commission = _commission(position.quantity * current_price, commission_rate)
    return position.equity_after_entry_commission + gross_pnl - exit_commission


def _close_position(
    *,
    position: PositionState,
    exit_time: datetime,
    reference_price: Decimal,
    commission_rate: Decimal,
    slippage_rate: Decimal,
    exit_reason: str = "signal",
) -> tuple[Decimal, dict[str, str | int]]:
    action: Literal["BUY", "SELL"] = "SELL" if position.side == "LONG" else "BUY"
    exit_price = _execution_price(reference_price, action=action, slippage_rate=slippage_rate)
    gross_pnl = (
        (exit_price - position.entry_price) * position.quantity
        if position.side == "LONG"
        else (position.entry_price - exit_price) * position.quantity
    )
    exit_commission = _commission(position.quantity * exit_price, commission_rate)
    net_pnl = gross_pnl - exit_commission
    equity_after_close = position.equity_after_entry_commission + net_pnl
    return equity_after_close, {
        "side": position.side,
        "entry_time": position.entry_time.astimezone(UTC).isoformat(),
        "exit_time": exit_time.astimezone(UTC).isoformat(),
        "exit_reason": exit_reason,
        "quantity": format(position.quantity, "f"),
        "entry_price": format(position.entry_price, "f"),
        "exit_price": format(exit_price, "f"),
        "gross_pnl": format(gross_pnl.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), "f"),
        "net_pnl": format(net_pnl.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), "f"),
        "commission": format((position.entry_commission + exit_commission).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), "f"),
        "slippage_bps": int((slippage_rate * BPS_DIVISOR).to_integral_value(rounding=ROUND_HALF_UP)),
    }


def _open_position(
    *,
    side: Literal["LONG", "SHORT"],
    timestamp: datetime,
    reference_price: Decimal,
    equity: Decimal,
    commission_rate: Decimal,
    slippage_rate: Decimal,
    stop_loss_distance: Decimal | None = None,
    take_profit_distance: Decimal | None = None,
) -> PositionState:
    action: Literal["BUY", "SELL"] = "BUY" if side == "LONG" else "SELL"
    entry_price = _execution_price(reference_price, action=action, slippage_rate=slippage_rate)
    quantity = (equity / entry_price).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    entry_commission = _commission(quantity * entry_price, commission_rate)
    if side == "LONG":
        stop_loss = entry_price - stop_loss_distance if stop_loss_distance is not None else None
        take_profit = entry_price + take_profit_distance if take_profit_distance is not None else None
    else:
        stop_loss = entry_price + stop_loss_distance if stop_loss_distance is not None else None
        take_profit = entry_price - take_profit_distance if take_profit_distance is not None else None
    return PositionState(
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        entry_time=timestamp,
        equity_after_entry_commission=equity - entry_commission,
        entry_commission=entry_commission,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def _positive_decimal_parameter(parameters: dict[str, object], key: str) -> Decimal | None:
    value = parameters.get(key)
    if value is None:
        return None
    decimal_value = Decimal(str(value))
    if decimal_value <= Decimal("0"):
        return None
    return decimal_value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _bar_exit_trigger(position: PositionState, bar: MarketBar) -> tuple[str, Decimal] | None:
    if position.side == "LONG":
        if position.stop_loss is not None and bar.low <= position.stop_loss:
            return "stop_loss", position.stop_loss
        if position.take_profit is not None and bar.high >= position.take_profit:
            return "take_profit", position.take_profit
        return None

    if position.stop_loss is not None and bar.high >= position.stop_loss:
        return "stop_loss", position.stop_loss
    if position.take_profit is not None and bar.low <= position.take_profit:
        return "take_profit", position.take_profit
    return None


def _serialize_equity_curve(points: list[list[str]]) -> list[tuple[datetime, Decimal]]:
    return [
        (datetime.fromisoformat(point[0]), Decimal(point[1]))
        for point in points
    ]


def _serialize_trade_log(trades: list[dict[str, str | int]]) -> list[BacktestTradeLogItemData]:
    items: list[BacktestTradeLogItemData] = []
    for trade in trades:
        items.append(
            BacktestTradeLogItemData(
                side=str(trade["side"]),
                entry_time=datetime.fromisoformat(str(trade["entry_time"])),
                exit_time=datetime.fromisoformat(str(trade["exit_time"])),
                quantity=Decimal(str(trade["quantity"])),
                entry_price=Decimal(str(trade["entry_price"])),
                exit_price=Decimal(str(trade["exit_price"])),
                gross_pnl=Decimal(str(trade["gross_pnl"])),
                net_pnl=Decimal(str(trade["net_pnl"])),
                commission=Decimal(str(trade["commission"])),
                slippage_bps=int(trade["slippage_bps"]),
            )
        )
    return items


def _serialize_backtest_summary(backtest_run: BacktestRun) -> BacktestListItemData:
    return BacktestListItemData(
        id=backtest_run.id,
        strategy_run_id=backtest_run.strategy_run_id,
        strategy_name=backtest_run.strategy_run.strategy_name,
        start_date=backtest_run.start_date,
        end_date=backtest_run.end_date,
        status=backtest_run.status,
        initial_capital=backtest_run.initial_capital,
        final_capital=backtest_run.final_capital,
        total_return=backtest_run.total_return,
        max_drawdown=backtest_run.max_drawdown,
        sharpe_ratio=backtest_run.sharpe_ratio,
        win_rate=backtest_run.win_rate,
        total_trades=backtest_run.total_trades,
        created_at=backtest_run.created_at,
        completed_at=backtest_run.completed_at,
    )


def _serialize_backtest_detail(backtest_run: BacktestRun) -> BacktestDetailData:
    detail = backtest_run.result_detail or {}
    return BacktestDetailData(
        **_serialize_backtest_summary(backtest_run).model_dump(),
        error_message=backtest_run.error_message,
        equity_curve=_serialize_equity_curve(detail.get("equity_curve", [])),
        trade_log=_serialize_trade_log(detail.get("trade_log", [])),
    )


def _metrics_from_equity_curve(initial_capital: Decimal, equity_curve: list[tuple[datetime, Decimal]]) -> tuple[Decimal, Decimal, Decimal]:
    if not equity_curve:
        return Decimal("0"), Decimal("0"), Decimal("0")
    final_capital = equity_curve[-1][1]
    total_return = _quantize_metric((final_capital - initial_capital) / initial_capital)
    peak = initial_capital
    max_drawdown = Decimal("0")
    periodic_returns: list[float] = []
    previous_equity = initial_capital
    for _, equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak > Decimal("0"):
            drawdown = (equity - peak) / peak
            if drawdown < max_drawdown:
                max_drawdown = drawdown
        if previous_equity > Decimal("0"):
            periodic_returns.append(float((equity - previous_equity) / previous_equity))
        previous_equity = equity

    if len(periodic_returns) < 2:
        sharpe_ratio = Decimal("0")
    else:
        mean_return = sum(periodic_returns) / len(periodic_returns)
        variance = sum((value - mean_return) ** 2 for value in periodic_returns) / (len(periodic_returns) - 1)
        sharpe_ratio = Decimal("0") if variance == 0 else Decimal(str(mean_return / math.sqrt(variance)))
    return total_return, _quantize_metric(max_drawdown), _quantize_metric(sharpe_ratio)


def _get_strategy(session: Session, strategy_run_id: UUID) -> StrategyRun:
    strategy = session.execute(
        select(StrategyRun).where(StrategyRun.id == strategy_run_id)
    ).scalar_one_or_none()
    if strategy is None:
        raise ApiException(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="Strategy run not found.",
            detail={"strategy_run_id": str(strategy_run_id)},
        )
    return strategy


def _load_bars(session: Session, start_date: date, end_date: date) -> list[MarketBar]:
    start_dt = datetime.combine(start_date, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    bars = session.execute(
        select(MarketBar)
        .where(
            MarketBar.symbol == CANONICAL_SYMBOL,
            MarketBar.timeframe == CANONICAL_TIMEFRAME,
            MarketBar.bar_time >= start_dt,
            MarketBar.bar_time < end_dt,
        )
        .order_by(MarketBar.bar_time.asc())
    ).scalars().all()
    if len(bars) < 2:
        raise BacktestDataInsufficientError(
            "Backtest requires at least two historical bars in the requested date range.",
            detail={
                "symbol": CANONICAL_SYMBOL,
                "timeframe": CANONICAL_TIMEFRAME,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
    return bars


def run_backtest(session: Session, payload: BacktestCreateRequest, *, persist: bool = True) -> BacktestRun:
    if payload.start_date > payload.end_date:
        raise ApiException(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message="start_date must be earlier than or equal to end_date.",
            detail={
                "start_date": payload.start_date.isoformat(),
                "end_date": payload.end_date.isoformat(),
            },
        )

    strategy = _get_strategy(session, payload.strategy_run_id)
    parameters = strategy.parameters or {}
    lookback_hours = int(parameters.get("lookback_hours", 24))
    momentum_bars = int(parameters.get("momentum_bars", 4))
    paper_parameters = parameters.get("paper", {})
    if not isinstance(paper_parameters, dict):
        paper_parameters = {}
    stop_loss_distance = _positive_decimal_parameter(paper_parameters, "stop_loss_distance")
    take_profit_distance = _positive_decimal_parameter(paper_parameters, "take_profit_distance")
    slippage_rate = Decimal(str(payload.slippage_bps)) / BPS_DIVISOR
    commission_rate = Decimal(str(payload.commission_bps)) / BPS_DIVISOR

    backtest_run = BacktestRun(
        strategy_run_id=strategy.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        initial_capital=payload.initial_capital,
        status="running",
        result_detail={
            "config": {
                "slippage_bps": payload.slippage_bps,
                "commission_bps": payload.commission_bps,
                "lookback_hours": lookback_hours,
                "momentum_bars": momentum_bars,
                "stop_loss_distance": format(stop_loss_distance, "f") if stop_loss_distance is not None else None,
                "take_profit_distance": format(take_profit_distance, "f") if take_profit_distance is not None else None,
            }
        },
    )
    if persist:
        session.add(backtest_run)
        session.flush()

    realized_equity = payload.initial_capital
    position: PositionState | None = None
    equity_curve: list[tuple[datetime, Decimal]] = []
    trade_log: list[dict[str, str | int]] = []
    signal_log: list[dict[str, object]] = []
    wins = 0

    try:
        bars = _load_bars(session, payload.start_date, payload.end_date)
        for bar in bars:
            if position is not None:
                exit_trigger = _bar_exit_trigger(position, bar)
                if exit_trigger is not None:
                    exit_reason, exit_reference_price = exit_trigger
                    realized_equity, closed_trade = _close_position(
                        position=position,
                        exit_time=bar.bar_time,
                        reference_price=exit_reference_price,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                        exit_reason=exit_reason,
                    )
                    trade_log.append(closed_trade)
                    wins += int(Decimal(str(closed_trade["net_pnl"])) > Decimal("0"))
                    position = None

            features = compute_features(
                session,
                CANONICAL_SYMBOL,
                bar.bar_time,
                lookback_hours,
                momentum_bars=momentum_bars,
            )
            decision = generate_signal(features, strategy, session=session)
            signal_log.append(
                {
                    "timestamp": bar.bar_time.astimezone(UTC).isoformat(),
                    "direction": decision.direction,
                    "reasoning": decision.reasoning,
                    "features_used": features.snapshot(),
                }
            )

            if decision.direction == "BUY":
                if position is not None and position.side == "SHORT":
                    realized_equity, closed_trade = _close_position(
                        position=position,
                        exit_time=bar.bar_time,
                        reference_price=bar.open,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                    )
                    trade_log.append(closed_trade)
                    wins += int(Decimal(str(closed_trade["net_pnl"])) > Decimal("0"))
                    position = None
                if position is None and decision.direction == "BUY":
                    position = _open_position(
                        side="LONG",
                        timestamp=bar.bar_time,
                        reference_price=bar.open,
                        equity=realized_equity,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                        stop_loss_distance=stop_loss_distance,
                        take_profit_distance=take_profit_distance,
                    )
            elif decision.direction == "SELL":
                if position is not None and position.side == "LONG":
                    realized_equity, closed_trade = _close_position(
                        position=position,
                        exit_time=bar.bar_time,
                        reference_price=bar.open,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                    )
                    trade_log.append(closed_trade)
                    wins += int(Decimal(str(closed_trade["net_pnl"])) > Decimal("0"))
                    position = None
                if position is None:
                    position = _open_position(
                        side="SHORT",
                        timestamp=bar.bar_time,
                        reference_price=bar.open,
                        equity=realized_equity,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                        stop_loss_distance=stop_loss_distance,
                        take_profit_distance=take_profit_distance,
                    )

            marked_equity = _current_equity(realized_equity, position, bar.close, commission_rate)
            equity_curve.append((bar.bar_time, marked_equity))

        if position is not None:
            realized_equity, closed_trade = _close_position(
                position=position,
                exit_time=bars[-1].bar_time,
                reference_price=bars[-1].close,
                commission_rate=commission_rate,
                slippage_rate=slippage_rate,
            )
            trade_log.append(closed_trade)
            wins += int(Decimal(str(closed_trade["net_pnl"])) > Decimal("0"))
            equity_curve[-1] = (bars[-1].bar_time, realized_equity)

        total_return, max_drawdown, sharpe_ratio = _metrics_from_equity_curve(payload.initial_capital, equity_curve)
        total_trades = len(trade_log)
        win_rate = Decimal("0") if total_trades == 0 else _quantize_rate(Decimal(wins) / Decimal(total_trades))
        backtest_run.final_capital = _quantize_money(realized_equity)
        backtest_run.total_return = total_return
        backtest_run.max_drawdown = max_drawdown
        backtest_run.sharpe_ratio = sharpe_ratio
        backtest_run.win_rate = win_rate
        backtest_run.total_trades = total_trades
        backtest_run.status = "completed"
        backtest_run.error_message = None
        backtest_run.result_detail = {
            "config": {
                "slippage_bps": payload.slippage_bps,
                "commission_bps": payload.commission_bps,
                "lookback_hours": lookback_hours,
                "momentum_bars": momentum_bars,
                "stop_loss_distance": format(stop_loss_distance, "f") if stop_loss_distance is not None else None,
                "take_profit_distance": format(take_profit_distance, "f") if take_profit_distance is not None else None,
            },
            "bars_processed": len(bars),
            "equity_curve": [[timestamp.astimezone(UTC).isoformat(), format(_quantize_money(equity), "f")] for timestamp, equity in equity_curve],
            "trade_log": trade_log,
            "signal_log": signal_log,
        }
        backtest_run.completed_at = utcnow()
        if persist:
            session.add(backtest_run)
            session.flush()
        return backtest_run
    except Exception as exc:
        backtest_run.status = "failed"
        backtest_run.error_message = str(exc)
        backtest_run.completed_at = utcnow()
        backtest_run.result_detail = {
            **(backtest_run.result_detail or {}),
            "bars_processed": len(equity_curve),
            "equity_curve": [
                [timestamp.astimezone(UTC).isoformat(), format(_quantize_money(equity), "f")]
                for timestamp, equity in equity_curve
            ],
            "trade_log": trade_log,
            "signal_log": signal_log,
        }
        if persist:
            session.add(backtest_run)
            session.flush()
        raise


def create_and_run_backtest(session: Session, payload: BacktestCreateRequest) -> BacktestCreateResponseData:
    try:
        backtest_run = run_backtest(session, payload)
    except BacktestDataInsufficientError as exc:
        session.commit()
        raise ApiException(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="BACKTEST_DATA_INSUFFICIENT",
            message=exc.message,
            detail=exc.detail,
        ) from exc
    except Exception:
        session.commit()
        raise

    session.commit()
    return BacktestCreateResponseData(
        backtest_id=backtest_run.id,
        status="pending",
        message="Backtest task queued",
    )


def get_backtest(session: Session, backtest_id: UUID) -> BacktestDetailData:
    backtest_run = session.execute(
        select(BacktestRun)
        .options(selectinload(BacktestRun.strategy_run))
        .where(BacktestRun.id == backtest_id)
    ).scalar_one_or_none()
    if backtest_run is None:
        raise ApiException(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="Backtest run not found.",
            detail={"backtest_id": str(backtest_id)},
        )
    return _serialize_backtest_detail(backtest_run)


def list_backtests(
    session: Session,
    *,
    page: int,
    page_size: int,
    strategy_run_id: UUID | None,
    status_value: BacktestStatus | None,
) -> PaginatedData[BacktestListItemData]:
    row_query = select(BacktestRun.id).select_from(BacktestRun)
    if strategy_run_id is not None:
        row_query = row_query.where(BacktestRun.strategy_run_id == strategy_run_id)
    if status_value is not None:
        row_query = row_query.where(BacktestRun.status == status_value)

    total = session.execute(select(func.count()).select_from(row_query.subquery())).scalar_one()
    ids = session.execute(
        row_query.order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    if not ids:
        return PaginatedData[BacktestListItemData](items=[], total=total, page=page, page_size=page_size)

    items = session.execute(
        select(BacktestRun)
        .options(selectinload(BacktestRun.strategy_run))
        .where(BacktestRun.id.in_(ids))
    ).scalars().all()
    by_id = {item.id: item for item in items}
    return PaginatedData[BacktestListItemData](
        items=[_serialize_backtest_summary(by_id[item_id]) for item_id in ids],
        total=total,
        page=page,
        page_size=page_size,
    )
