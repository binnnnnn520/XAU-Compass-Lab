from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from celery.schedules import crontab
from sqlalchemy import select

from app.celery_app import celery_app
from app.models import AuditLog, MarketBar, NewsItem, PaperOrder, PaperPosition, RiskEvent, SentimentScore, Signal, StrategyRun
from app.services.paper_execution import execute_signal
from app.services.risk_engine import evaluate_signal_risk


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


def _strategy(*, risk: dict | None = None, paper: dict | None = None) -> StrategyRun:
    return StrategyRun(
        strategy_name="paper_strategy_v1",
        version="1.0.0",
        parameters={
            "risk": risk or {},
            "paper": paper or {"initial_capital": "100000.00", "order_quantity": "1.00000000"},
        },
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
        reasoning="Task 10 fixture",
    )


def _negative_sentiment(*, timestamp: datetime, suffix: int) -> tuple[NewsItem, SentimentScore]:
    item = NewsItem(
        title=f"Negative fixture {suffix}",
        published_at=timestamp,
        title_hash=f"{suffix}".zfill(64),
        status="analyzed",
    )
    sentiment = SentimentScore(
        news_item=item,
        analyzer_type=f"rule_based_{suffix}",
        sentiment="negative",
        score=Decimal("-0.9000"),
        confidence=Decimal("0.9000"),
        created_at=timestamp,
    )
    return item, sentiment


def test_execute_signal_pass_flow_updates_positions_and_audit_logs(db_session) -> None:
    strategy = _strategy()
    buy_time = datetime(2026, 4, 8, 8, 0, tzinfo=UTC)
    sell_time = buy_time + timedelta(hours=1)
    db_session.add(strategy)
    db_session.commit()
    db_session.add_all(
        [
            _market_bar(timestamp=buy_time, close_price="2300.00000000"),
            _market_bar(timestamp=sell_time, close_price="2315.00000000"),
        ]
    )
    db_session.commit()

    buy_signal = _signal(strategy=strategy, timestamp=buy_time, direction="BUY", price="2300.00000000")
    sell_signal = _signal(strategy=strategy, timestamp=sell_time, direction="SELL", price="2315.00000000")
    db_session.add_all([buy_signal, sell_signal])
    db_session.commit()

    buy_order = execute_signal(db_session, buy_signal.id)
    db_session.commit()
    assert buy_order.status == "filled"

    sell_order = execute_signal(db_session, sell_signal.id)
    db_session.commit()
    assert sell_order.status == "filled"

    positions = db_session.execute(select(PaperPosition).order_by(PaperPosition.created_at.asc())).scalars().all()
    assert len(positions) == 1
    assert positions[0].status == "closed"
    assert positions[0].closed_at == sell_time
    assert positions[0].realized_pnl == Decimal("15.00000000")

    audit_actions = db_session.execute(select(AuditLog.action).order_by(AuditLog.created_at.asc())).scalars().all()
    assert "order_created" in audit_actions
    assert "risk_passed" in audit_actions
    assert "order_filled" in audit_actions
    assert "position_changed" in audit_actions


def test_execute_signal_applies_configured_stops_to_order_and_open_position(db_session) -> None:
    strategy = _strategy(
        paper={
            "initial_capital": "100000.00",
            "order_quantity": "1.00000000",
            "stop_loss_distance": "10.00000000",
            "take_profit_distance": "20.00000000",
            "trailing_stop_distance": "5.00000000",
        }
    )
    signal_time = datetime(2026, 4, 29, 8, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(_market_bar(timestamp=signal_time, close_price="2300.00000000"))
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="2300.00000000")
    db_session.add(signal)
    db_session.commit()

    order = execute_signal(db_session, signal.id)
    db_session.commit()

    assert order.status == "filled"
    assert order.stop_loss == Decimal("2290.00000000")
    assert order.take_profit == Decimal("2320.00000000")

    position = db_session.execute(select(PaperPosition).where(PaperPosition.status == "open")).scalar_one()
    assert position.stop_loss == Decimal("2290.00000000")
    assert position.take_profit == Decimal("2320.00000000")
    assert position.trailing_stop_distance == Decimal("5.00000000")
    assert position.trailing_stop_price == Decimal("2295.00000000")


def test_position_monitor_closes_long_position_when_stop_loss_hits(db_session) -> None:
    from app.services.paper_execution.position_monitor import check_open_position_stops

    strategy = _strategy()
    signal_time = datetime(2026, 4, 29, 9, 0, tzinfo=UTC)
    check_time = signal_time + timedelta(minutes=30)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(_market_bar(timestamp=signal_time, close_price="2300.00000000"))
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="2300.00000000")
    db_session.add(signal)
    db_session.commit()
    entry_order = PaperOrder(
        signal_id=signal.id,
        symbol="XAUUSD",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("1.00000000"),
        price=Decimal("2300.00000000"),
        stop_loss=Decimal("2290.00000000"),
        take_profit=Decimal("2320.00000000"),
        status="filled",
        filled_at=signal_time,
    )
    db_session.add(entry_order)
    db_session.flush()
    position = PaperPosition(
        symbol="XAUUSD",
        side="LONG",
        quantity=Decimal("1.00000000"),
        entry_price=Decimal("2300.00000000"),
        current_price=Decimal("2300.00000000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        status="open",
        opened_at=signal_time,
        entry_order_id=entry_order.id,
        stop_loss=Decimal("2290.00000000"),
        take_profit=Decimal("2320.00000000"),
        trailing_stop_distance=Decimal("5.00000000"),
        trailing_stop_price=Decimal("2295.00000000"),
    )
    db_session.add(position)
    db_session.add(_market_bar(timestamp=check_time, close_price="2289.00000000"))
    db_session.commit()

    closed_count = check_open_position_stops(db_session, as_of=check_time)
    db_session.commit()

    assert closed_count == 1
    db_session.refresh(position)
    assert position.status == "closed"
    assert position.closed_at == check_time
    assert position.current_price == Decimal("2289.00000000")
    assert position.realized_pnl == Decimal("-11.00000000")

    exit_order = db_session.execute(
        select(PaperOrder).where(PaperOrder.id == position.exit_order_id)
    ).scalar_one()
    assert exit_order.side == "SELL"
    assert exit_order.status == "filled"
    assert exit_order.price == Decimal("2289.00000000")

    risk_event = db_session.execute(select(RiskEvent).order_by(RiskEvent.created_at.desc())).scalar_one()
    assert risk_event.event_type == "stop_loss_triggered"
    assert risk_event.action_taken == "close_position"
    assert risk_event.related_order_id == exit_order.id

    audit_log = db_session.execute(
        select(AuditLog).where(AuditLog.action == "position_stop_triggered").order_by(AuditLog.created_at.desc())
    ).scalar_one()
    assert audit_log.entity_id == position.id


def test_position_monitor_closes_short_position_when_take_profit_hits(db_session) -> None:
    from app.services.paper_execution.position_monitor import check_open_position_stops

    strategy = _strategy()
    signal_time = datetime(2026, 4, 29, 10, 0, tzinfo=UTC)
    check_time = signal_time + timedelta(minutes=30)
    db_session.add(strategy)
    db_session.commit()
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="SELL", price="2300.00000000")
    db_session.add(signal)
    db_session.commit()
    entry_order = PaperOrder(
        signal_id=signal.id,
        symbol="XAUUSD",
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("1.00000000"),
        price=Decimal("2300.00000000"),
        status="filled",
        filled_at=signal_time,
    )
    db_session.add(entry_order)
    db_session.flush()
    position = PaperPosition(
        symbol="XAUUSD",
        side="SHORT",
        quantity=Decimal("1.00000000"),
        entry_price=Decimal("2300.00000000"),
        current_price=Decimal("2300.00000000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        status="open",
        opened_at=signal_time,
        entry_order_id=entry_order.id,
        stop_loss=Decimal("2310.00000000"),
        take_profit=Decimal("2280.00000000"),
    )
    db_session.add(position)
    db_session.add(_market_bar(timestamp=check_time, close_price="2279.00000000"))
    db_session.commit()

    closed_count = check_open_position_stops(db_session, as_of=check_time)
    db_session.commit()

    assert closed_count == 1
    db_session.refresh(position)
    assert position.status == "closed"
    assert position.realized_pnl == Decimal("21.00000000")
    exit_order = db_session.execute(select(PaperOrder).where(PaperOrder.id == position.exit_order_id)).scalar_one()
    assert exit_order.side == "BUY"
    risk_event = db_session.execute(select(RiskEvent).order_by(RiskEvent.created_at.desc())).scalar_one()
    assert risk_event.event_type == "take_profit_triggered"
    assert risk_event.related_order_id == exit_order.id


def test_position_monitor_raises_long_trailing_stop_then_closes_on_reversal(db_session) -> None:
    from app.services.paper_execution.position_monitor import check_open_position_stops

    strategy = _strategy()
    signal_time = datetime(2026, 4, 29, 11, 0, tzinfo=UTC)
    trail_time = signal_time + timedelta(minutes=15)
    reverse_time = signal_time + timedelta(minutes=30)
    db_session.add(strategy)
    db_session.commit()
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="2300.00000000")
    db_session.add(signal)
    db_session.commit()
    entry_order = PaperOrder(
        signal_id=signal.id,
        symbol="XAUUSD",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("1.00000000"),
        price=Decimal("2300.00000000"),
        status="filled",
        filled_at=signal_time,
    )
    db_session.add(entry_order)
    db_session.flush()
    position = PaperPosition(
        symbol="XAUUSD",
        side="LONG",
        quantity=Decimal("1.00000000"),
        entry_price=Decimal("2300.00000000"),
        current_price=Decimal("2300.00000000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        status="open",
        opened_at=signal_time,
        entry_order_id=entry_order.id,
        trailing_stop_distance=Decimal("5.00000000"),
        trailing_stop_price=Decimal("2295.00000000"),
    )
    db_session.add(position)
    db_session.add(_market_bar(timestamp=trail_time, close_price="2310.00000000"))
    db_session.commit()

    assert check_open_position_stops(db_session, as_of=trail_time) == 0
    db_session.commit()
    db_session.refresh(position)
    assert position.status == "open"
    assert position.trailing_stop_price == Decimal("2305.00000000")

    db_session.add(_market_bar(timestamp=reverse_time, close_price="2304.00000000"))
    db_session.commit()
    assert check_open_position_stops(db_session, as_of=reverse_time) == 1
    db_session.commit()
    db_session.refresh(position)
    assert position.status == "closed"
    assert position.realized_pnl == Decimal("4.00000000")
    risk_event = db_session.execute(select(RiskEvent).order_by(RiskEvent.created_at.desc())).scalar_one()
    assert risk_event.event_type == "trailing_stop_triggered"


def test_position_monitor_closes_position_past_max_holding_time(db_session) -> None:
    from app.services.paper_execution.position_monitor import check_open_position_stops

    strategy = _strategy(risk={"max_position_holding_hours": 2})
    signal_time = datetime(2026, 4, 29, 5, 0, tzinfo=UTC)
    check_time = signal_time + timedelta(hours=3)
    db_session.add(strategy)
    db_session.commit()
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="2300.00000000")
    db_session.add(signal)
    db_session.commit()
    entry_order = PaperOrder(
        signal_id=signal.id,
        symbol="XAUUSD",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("1.00000000"),
        price=Decimal("2300.00000000"),
        status="filled",
        filled_at=signal_time,
    )
    db_session.add(entry_order)
    db_session.flush()
    position = PaperPosition(
        symbol="XAUUSD",
        side="LONG",
        quantity=Decimal("1.00000000"),
        entry_price=Decimal("2300.00000000"),
        current_price=Decimal("2300.00000000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        status="open",
        opened_at=signal_time,
        entry_order_id=entry_order.id,
    )
    db_session.add(position)
    db_session.add(_market_bar(timestamp=check_time, close_price="2301.00000000"))
    db_session.commit()

    assert check_open_position_stops(db_session, as_of=check_time) == 1
    db_session.commit()

    db_session.refresh(position)
    assert position.status == "closed"
    assert position.realized_pnl == Decimal("1.00000000")
    risk_event = db_session.execute(select(RiskEvent).order_by(RiskEvent.created_at.desc())).scalar_one()
    assert risk_event.event_type == "max_holding_time_triggered"
    assert risk_event.action_taken == "close_position"


def test_position_monitor_closes_position_when_single_position_loss_exceeds_limit(db_session) -> None:
    from app.services.paper_execution.position_monitor import check_open_position_stops

    strategy = _strategy(risk={"max_position_loss_pct": "0.030000"})
    signal_time = datetime(2026, 4, 29, 6, 0, tzinfo=UTC)
    check_time = signal_time + timedelta(minutes=30)
    db_session.add(strategy)
    db_session.commit()
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="100.00000000")
    db_session.add(signal)
    db_session.commit()
    entry_order = PaperOrder(
        signal_id=signal.id,
        symbol="XAUUSD",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("1.00000000"),
        price=Decimal("100.00000000"),
        status="filled",
        filled_at=signal_time,
    )
    db_session.add(entry_order)
    db_session.flush()
    position = PaperPosition(
        symbol="XAUUSD",
        side="LONG",
        quantity=Decimal("1.00000000"),
        entry_price=Decimal("100.00000000"),
        current_price=Decimal("100.00000000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        status="open",
        opened_at=signal_time,
        entry_order_id=entry_order.id,
    )
    db_session.add(position)
    db_session.add(_market_bar(timestamp=check_time, close_price="96.00000000"))
    db_session.commit()

    assert check_open_position_stops(db_session, as_of=check_time) == 1
    db_session.commit()

    db_session.refresh(position)
    assert position.status == "closed"
    assert position.realized_pnl == Decimal("-4.00000000")
    risk_event = db_session.execute(select(RiskEvent).order_by(RiskEvent.created_at.desc())).scalar_one()
    assert risk_event.event_type == "max_position_loss_triggered"
    assert risk_event.trigger_value == Decimal("-0.040000")
    assert risk_event.threshold_value == Decimal("-0.030000")


def test_task_check_stops_runs_without_real_broker(monkeypatch) -> None:
    from app.tasks.paper import task_check_stops

    class FakeSession:
        def close(self) -> None:
            return None

        def commit(self) -> None:
            return None

    class FakeSessionFactory:
        def configure(self, **kwargs) -> None:
            return None

        def __call__(self) -> FakeSession:
            return FakeSession()

    class FakeEngine:
        def dispose(self) -> None:
            return None

    captured: dict[str, object] = {}

    monkeypatch.setattr("app.tasks.paper.get_engine", lambda: FakeEngine())
    monkeypatch.setattr("app.tasks.paper.SessionLocal", FakeSessionFactory())

    def fake_check_open_position_stops(session, *, as_of=None):
        captured["as_of"] = as_of
        return 2

    monkeypatch.setattr("app.tasks.paper.check_open_position_stops", fake_check_open_position_stops)

    result = task_check_stops(as_of_iso="2026-04-29T12:00:00Z")

    assert result["positions_closed"] == 2
    assert result["checked_at"] == "2026-04-29T12:00:00+00:00"
    assert captured["as_of"] == datetime(2026, 4, 29, 12, 0, tzinfo=UTC)


def test_celery_beat_schedule_wires_position_stop_task_every_minute() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["check-paper-position-stops-every-minute"]["task"] == "app.tasks.paper.task_check_stops"
    assert schedule["check-paper-position-stops-every-minute"]["schedule"] == crontab(minute="*")
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"


def test_execute_signal_rejection_persists_risk_records(db_session) -> None:
    strategy = _strategy(
        risk={
            "circuit_breaker_threshold": "-0.7000",
            "circuit_breaker_min_count": 5,
            "circuit_breaker_window_hours": 1,
        }
    )
    signal_time = datetime(2026, 4, 8, 9, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(_market_bar(timestamp=signal_time, close_price="2280.00000000"))
    for index in range(5):
        item, sentiment = _negative_sentiment(timestamp=signal_time - timedelta(minutes=10 * (index + 1)), suffix=index + 1)
        db_session.add_all([item, sentiment])
    db_session.commit()

    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="2280.00000000")
    db_session.add(signal)
    db_session.commit()

    order = execute_signal(db_session, signal.id)
    db_session.commit()

    assert order.status == "rejected"
    assert order.reject_reason == "circuit_breaker_active"
    risk_event = db_session.execute(select(RiskEvent).order_by(RiskEvent.created_at.desc())).scalar_one()
    assert risk_event.event_type == "circuit_breaker"
    assert risk_event.related_order_id == order.id
    rejected_log = db_session.execute(
        select(AuditLog).where(AuditLog.action == "risk_rejected").order_by(AuditLog.created_at.desc())
    ).scalar_one()
    assert rejected_log.entity_id == order.id


def test_risk_engine_rejects_max_drawdown_breach(db_session) -> None:
    strategy = _strategy(paper={"initial_capital": "100.00", "order_quantity": "1.00000000"})
    signal_time = datetime(2026, 4, 8, 10, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(_market_bar(timestamp=signal_time, close_price="50.00000000"))
    db_session.commit()
    position = PaperPosition(
        symbol="XAUUSD",
        side="LONG",
        quantity=Decimal("1.00000000"),
        entry_price=Decimal("100.00000000"),
        current_price=Decimal("50.00000000"),
        unrealized_pnl=Decimal("-50.00000000"),
        realized_pnl=Decimal("0"),
        status="open",
        opened_at=signal_time - timedelta(hours=1),
    )
    db_session.add(position)
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="50.00000000")
    db_session.add(signal)
    db_session.commit()

    decision = evaluate_signal_risk(db_session, signal, quantity=Decimal("1.00000000"), reference_price=Decimal("50"))

    assert decision.passed is False
    assert decision.reject_reason == "max_drawdown_breach"
    assert decision.event_payload is not None
    assert decision.event_payload.event_type == "max_drawdown_breach"


def test_risk_engine_rejects_open_position_limit(db_session) -> None:
    strategy = _strategy(risk={"max_open_positions": 3})
    signal_time = datetime(2026, 4, 8, 11, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(_market_bar(timestamp=signal_time, close_price="2301.00000000"))
    db_session.add_all(
        [
            PaperPosition(
                symbol="XAUUSD",
                side="LONG",
                quantity=Decimal("1.00000000"),
                entry_price=Decimal("2300.00000000"),
                current_price=Decimal("2301.00000000"),
                status="open",
                opened_at=signal_time - timedelta(hours=3),
            ),
                PaperPosition(
                    symbol="XAUUSD",
                    side="LONG",
                    quantity=Decimal("1.00000000"),
                    entry_price=Decimal("2295.00000000"),
                    current_price=Decimal("2301.00000000"),
                status="open",
                opened_at=signal_time - timedelta(hours=2),
            ),
            PaperPosition(
                symbol="XAUUSD",
                side="LONG",
                quantity=Decimal("1.00000000"),
                entry_price=Decimal("2298.00000000"),
                current_price=Decimal("2301.00000000"),
                status="open",
                opened_at=signal_time - timedelta(hours=1),
            ),
        ]
    )
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="2301.00000000")
    db_session.add(signal)
    db_session.commit()

    decision = evaluate_signal_risk(db_session, signal, quantity=Decimal("1.00000000"), reference_price=Decimal("2301"))

    assert decision.passed is False
    assert decision.reject_reason == "max_positions_reached"


def test_risk_engine_rejects_direction_concentration_for_new_same_side_position(db_session) -> None:
    strategy = _strategy(risk={"max_open_positions": 10, "max_same_direction_positions": 2})
    signal_time = datetime(2026, 4, 29, 13, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(_market_bar(timestamp=signal_time, close_price="2301.00000000"))
    db_session.add_all(
        [
            PaperPosition(
                symbol="XAUUSD",
                side="LONG",
                quantity=Decimal("1.00000000"),
                entry_price=Decimal("2300.00000000"),
                current_price=Decimal("2301.00000000"),
                status="open",
                opened_at=signal_time - timedelta(hours=2),
            ),
            PaperPosition(
                symbol="XAUUSD",
                side="LONG",
                quantity=Decimal("1.00000000"),
                entry_price=Decimal("2295.00000000"),
                current_price=Decimal("2301.00000000"),
                status="open",
                opened_at=signal_time - timedelta(hours=1),
            ),
        ]
    )
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="2301.00000000")
    db_session.add(signal)
    db_session.commit()

    decision = evaluate_signal_risk(db_session, signal, quantity=Decimal("1.00000000"), reference_price=Decimal("2301"))

    assert decision.passed is False
    assert decision.reject_reason == "direction_concentration_exceeded"
    assert decision.event_payload is not None
    assert decision.event_payload.event_type == "direction_concentration_exceeded"


def test_risk_engine_rejects_per_trade_risk(db_session) -> None:
    strategy = _strategy(
        risk={"estimated_volatility": "0.5000", "max_risk_per_trade": "0.0100"},
        paper={"initial_capital": "1000.00", "order_quantity": "1.00000000"},
    )
    signal_time = datetime(2026, 4, 8, 12, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(_market_bar(timestamp=signal_time, close_price="100.00000000"))
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="BUY", price="100.00000000")
    db_session.add(signal)
    db_session.commit()

    decision = evaluate_signal_risk(db_session, signal, quantity=Decimal("1.00000000"), reference_price=Decimal("100"))

    assert decision.passed is False
    assert decision.reject_reason == "risk_per_trade_exceeded"


def test_risk_engine_allows_close_only_order_during_circuit_breaker(db_session) -> None:
    strategy = _strategy()
    signal_time = datetime(2026, 4, 8, 13, 0, tzinfo=UTC)
    db_session.add(strategy)
    db_session.commit()
    db_session.add(_market_bar(timestamp=signal_time, close_price="2280.00000000"))
    db_session.add(
        PaperPosition(
            symbol="XAUUSD",
            side="LONG",
            quantity=Decimal("1.00000000"),
            entry_price=Decimal("2300.00000000"),
            current_price=Decimal("2280.00000000"),
            status="open",
            opened_at=signal_time - timedelta(hours=1),
        )
    )
    for index in range(5):
        item, sentiment = _negative_sentiment(timestamp=signal_time - timedelta(minutes=10 * (index + 1)), suffix=10 + index)
        db_session.add_all([item, sentiment])
    signal = _signal(strategy=strategy, timestamp=signal_time, direction="SELL", price="2280.00000000")
    db_session.add(signal)
    db_session.commit()

    decision = evaluate_signal_risk(db_session, signal, quantity=Decimal("1.00000000"), reference_price=Decimal("2280"))

    assert decision.passed is True
    assert decision.checks_result["close_only"] is True
