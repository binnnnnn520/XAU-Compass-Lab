from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import sys

from sqlalchemy import select


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.models import MarketBar, PaperOrder, PaperPosition, Signal, StrategyRun
from app.services.broker import IBKRBroker, MT5Broker, PaperBroker


def _strategy() -> StrategyRun:
    return StrategyRun(
        strategy_name="broker_strategy_v1",
        version="1.0.0",
        parameters={"paper": {"initial_capital": "100000.00", "order_quantity": "1.00000000"}},
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
        reasoning="Broker fixture",
    )


def test_paper_broker_place_order_persists_existing_paper_tables(db_session) -> None:
    strategy = _strategy()
    signal_time = datetime(2026, 4, 30, 2, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(
        MarketBar(
            timeframe="1h",
            bar_time=signal_time,
            open=Decimal("2300.00000000"),
            high=Decimal("2300.00000000"),
            low=Decimal("2300.00000000"),
            close=Decimal("2300.00000000"),
            volume=Decimal("10.00000000"),
        )
    )
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="2300.00000000")
    db_session.add(signal)
    db_session.commit()

    broker = PaperBroker(db_session, signal_id=signal.id, fill_time=signal_time)
    result = broker.place_order(
        symbol="XAUUSD",
        side="BUY",
        quantity=Decimal("1.00000000"),
        price=Decimal("2300.00000000"),
        stop_loss=Decimal("2290.00000000"),
        take_profit=Decimal("2320.00000000"),
    )
    db_session.commit()

    assert result.accepted is True
    assert result.status == "filled"

    order = db_session.execute(select(PaperOrder)).scalar_one()
    assert str(order.id) == result.order_id
    assert order.stop_loss == Decimal("2290.00000000")
    assert order.take_profit == Decimal("2320.00000000")

    position = db_session.execute(select(PaperPosition)).scalar_one()
    assert position.entry_order_id == order.id
    assert position.status == "open"
    assert position.stop_loss == Decimal("2290.00000000")
    assert position.take_profit == Decimal("2320.00000000")


def test_paper_broker_cancel_order_only_allows_pending_orders(db_session) -> None:
    strategy = _strategy()
    signal_time = datetime(2026, 4, 30, 3, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="2300.00000000")
    db_session.add(signal)
    db_session.commit()
    order = PaperOrder(
        signal_id=signal.id,
        symbol="XAUUSD",
        side="BUY",
        order_type="LIMIT",
        quantity=Decimal("1.00000000"),
        limit_price=Decimal("2295.00000000"),
        status="pending",
    )
    db_session.add(order)
    db_session.commit()

    broker = PaperBroker(db_session)

    assert broker.cancel_order(str(order.id)) is True
    db_session.refresh(order)
    assert order.status == "cancelled"


def test_placeholder_live_brokers_are_not_implemented() -> None:
    for broker in (MT5Broker(), IBKRBroker()):
        try:
            broker.get_account()
        except NotImplementedError:
            continue
        raise AssertionError("Live broker placeholders must not be usable before Phase 5.")
