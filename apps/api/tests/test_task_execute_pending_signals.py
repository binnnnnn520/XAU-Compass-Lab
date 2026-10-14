from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models import MarketBar, PaperOrder, Signal, StrategyRun
from app.services.paper_execution import execute_pending_signals


def _market_bar(*, timestamp: datetime, close_price: str) -> MarketBar:
    close_decimal = Decimal(close_price)
    return MarketBar(
        timeframe="1h",
        bar_time=timestamp,
        open=close_decimal,
        high=close_decimal,
        low=close_decimal,
        close=close_decimal,
        volume=Decimal("10.00000000"),
    )


def _strategy() -> StrategyRun:
    return StrategyRun(
        strategy_name="paper_strategy_v1",
        version="1.0.0",
        parameters={"risk": {}, "paper": {"initial_capital": "100000.00", "order_quantity": "1.00000000"}},
        is_active=True,
    )


def _signal(*, strategy: StrategyRun, timestamp: datetime, direction: str, price: str) -> Signal:
    return Signal(
        strategy_run_id=strategy.id,
        signal_time=timestamp,
        direction=direction,
        strength=Decimal("0.8000"),
        confidence=Decimal("0.7500"),
        price_at_signal=Decimal(price),
        features_used={"sentiment_mean": "0.1000"},
        reasoning="pending-signals fixture",
    )


def test_execute_pending_signals_fills_actionable_and_skips_hold(db_session) -> None:
    strategy = _strategy()
    buy_time = datetime(2026, 4, 8, 8, 0, tzinfo=UTC)
    hold_time = buy_time + timedelta(hours=1)
    db_session.add(strategy)
    db_session.commit()
    db_session.add_all(
        [
            _market_bar(timestamp=buy_time, close_price="2300.00000000"),
            _market_bar(timestamp=hold_time, close_price="2305.00000000"),
        ]
    )
    db_session.commit()

    buy_signal = _signal(strategy=strategy, timestamp=buy_time, direction="BUY", price="2300.00000000")
    hold_signal = _signal(strategy=strategy, timestamp=hold_time, direction="HOLD", price="2305.00000000")
    db_session.add_all([buy_signal, hold_signal])
    db_session.commit()

    result = execute_pending_signals(db_session, limit=50)
    db_session.commit()

    assert result["candidates"] == 1
    assert result["filled"] == 1

    orders = db_session.execute(select(PaperOrder)).scalars().all()
    assert len(orders) == 1
    assert orders[0].signal_id == buy_signal.id
    assert orders[0].status == "filled"

    # The HOLD signal must never produce a paper order.
    hold_orders = db_session.execute(
        select(PaperOrder).where(PaperOrder.signal_id == hold_signal.id)
    ).scalars().all()
    assert hold_orders == []


def test_execute_pending_signals_is_idempotent(db_session) -> None:
    strategy = _strategy()
    buy_time = datetime(2026, 4, 8, 8, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(_market_bar(timestamp=buy_time, close_price="2300.00000000"))
    db_session.commit()
    buy_signal = _signal(strategy=strategy, timestamp=buy_time, direction="BUY", price="2300.00000000")
    db_session.add(buy_signal)
    db_session.commit()

    first = execute_pending_signals(db_session, limit=50)
    db_session.commit()
    assert first["candidates"] == 1
    assert first["filled"] == 1

    # A second run finds no new candidate because the signal already has an order.
    second = execute_pending_signals(db_session, limit=50)
    db_session.commit()
    assert second["candidates"] == 0
    assert second["filled"] == 0

    orders = db_session.execute(
        select(PaperOrder).where(PaperOrder.signal_id == buy_signal.id)
    ).scalars().all()
    assert len(orders) == 1
