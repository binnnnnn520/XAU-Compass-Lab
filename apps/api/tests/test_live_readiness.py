from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from celery.schedules import crontab
from sqlalchemy import select

from app.celery_app import celery_app
from app.models import AuditLog, LiveParallelObservation, PaperOrder, Signal, StrategyRun
from app.services.broker import IBKRPaperSandboxOrderLifecycleDryRun
from app.services.live_readiness import (
    LiveBrokerRoutingRequest,
    ParallelRunObservation,
    LiveOrderRequest,
    build_paper_live_divergence_report,
    build_gray_release_report_snapshot,
    build_persisted_parallel_run_report,
    collect_parallel_run_observations,
    evaluate_live_order_readiness,
    evaluate_live_broker_routing,
    load_live_readiness_config,
    record_parallel_run_observation,
    record_live_readiness_setting_change,
)


class CollectingDryRunBroker:
    is_available = True

    def __init__(self) -> None:
        self.requests: list[tuple[LiveOrderRequest, LiveBrokerRoutingRequest]] = []

    def dry_run_order_lifecycle(
        self,
        *,
        config,
        order_request: LiveOrderRequest,
        routing_request: LiveBrokerRoutingRequest,
        submitted_at: datetime,
        cancel_requested_at=None,
    ) -> IBKRPaperSandboxOrderLifecycleDryRun:
        self.requests.append((order_request, routing_request))
        return IBKRPaperSandboxOrderLifecycleDryRun(
            accepted=True,
            status="accepted",
            reject_reason=None,
            lifecycle=["submitted", "accepted"],
            submitted_at=submitted_at,
            cancel_requested_at=None,
            symbol=order_request.symbol,
            side=order_request.side,
            quantity=order_request.quantity,
            price=order_request.price,
            order_notional=Decimal("230.00000000"),
            diagnostics={"dry_run": True},
        )


def _phase5_strategy() -> StrategyRun:
    return StrategyRun(
        strategy_name="phase5_parallel_collection",
        version="1.0.0",
        parameters={},
        is_active=True,
    )


def _phase5_signal(strategy: StrategyRun, *, signal_time: datetime) -> Signal:
    return Signal(
        strategy_run_id=strategy.id,
        symbol="XAUUSD",
        signal_time=signal_time,
        direction="BUY",
        strength=Decimal("0.8000"),
        confidence=Decimal("0.9500"),
        price_at_signal=Decimal("2300.00000000"),
        features_used={"phase5": "parallel_collection"},
        reasoning="Phase 5 parallel collection fixture",
        source_type="live",
    )


def test_live_readiness_blocks_live_orders_by_default() -> None:
    config = load_live_readiness_config({})
    request = LiveOrderRequest(
        symbol="XAUUSD",
        side="BUY",
        quantity=Decimal("1.00000000"),
        price=Decimal("2300.00000000"),
        confidence=Decimal("0.9000"),
        daily_notional_so_far=Decimal("0.00000000"),
        total_equity=Decimal("100000.00000000"),
    )

    decision = evaluate_live_order_readiness(config, request)

    assert decision.passed is False
    assert decision.reject_reason == "live_trading_disabled"
    assert decision.requires_manual_approval is True


def test_live_readiness_forces_manual_approval_even_when_config_disables_it() -> None:
    config = load_live_readiness_config(
        {
            "live": {
                "enabled": True,
                "kill_switch_enabled": False,
                "manual_approval_required": False,
                "daily_notional_limit": "10000.00000000",
                "max_initial_capital_fraction": "0.0100",
            }
        }
    )
    request = LiveOrderRequest(
        symbol="XAUUSD",
        side="BUY",
        quantity=Decimal("0.10000000"),
        price=Decimal("2300.00000000"),
        confidence=Decimal("0.9500"),
        daily_notional_so_far=Decimal("0.00000000"),
        total_equity=Decimal("100000.00000000"),
    )

    decision = evaluate_live_order_readiness(config, request)

    assert decision.passed is True
    assert decision.requires_manual_approval is True
    assert decision.checks["manual_approval_required"] is True


def test_live_readiness_rejects_daily_notional_limit_breach() -> None:
    config = load_live_readiness_config(
        {
            "live": {
                "enabled": True,
                "kill_switch_enabled": False,
                "daily_notional_limit": "1000.00000000",
            }
        }
    )
    request = LiveOrderRequest(
        symbol="XAUUSD",
        side="BUY",
        quantity=Decimal("1.00000000"),
        price=Decimal("2300.00000000"),
        confidence=Decimal("0.9500"),
        daily_notional_so_far=Decimal("0.00000000"),
        total_equity=Decimal("100000.00000000"),
    )

    decision = evaluate_live_order_readiness(config, request)

    assert decision.passed is False
    assert decision.reject_reason == "daily_notional_limit_exceeded"
    assert decision.checks["projected_daily_notional"] == "2300.00000000"


def test_live_readiness_rejects_initial_capital_fraction_breach() -> None:
    config = load_live_readiness_config(
        {
            "live": {
                "enabled": True,
                "kill_switch_enabled": False,
                "daily_notional_limit": "10000.00000000",
                "max_initial_capital_fraction": "0.0100",
            }
        }
    )
    request = LiveOrderRequest(
        symbol="XAUUSD",
        side="BUY",
        quantity=Decimal("1.00000000"),
        price=Decimal("2300.00000000"),
        confidence=Decimal("0.9500"),
        daily_notional_so_far=Decimal("0.00000000"),
        total_equity=Decimal("100000.00000000"),
    )

    decision = evaluate_live_order_readiness(config, request)

    assert decision.passed is False
    assert decision.reject_reason == "initial_capital_fraction_exceeded"
    assert decision.checks["max_order_notional"] == "1000.00000000"


def test_paper_live_divergence_report_uses_decimal_slippage_and_utc_latency() -> None:
    base_time = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    report = build_paper_live_divergence_report(
        [
            ParallelRunObservation(
                signal_id="signal-1",
                signal_time=base_time,
                paper_direction="BUY",
                live_direction="BUY",
                paper_order_time=base_time + timedelta(seconds=1),
                live_order_time=base_time + timedelta(seconds=3),
                paper_fill_price=Decimal("2300.00000000"),
                live_fill_price=Decimal("2302.30000000"),
            ),
            ParallelRunObservation(
                signal_id="signal-2",
                signal_time=base_time + timedelta(minutes=1),
                paper_direction="BUY",
                live_direction="SELL",
                paper_order_time=base_time + timedelta(minutes=1, seconds=2),
                live_order_time=base_time + timedelta(minutes=1, seconds=5),
                paper_fill_price=Decimal("2300.00000000"),
                live_fill_price=Decimal("2297.70000000"),
            ),
        ],
        running_days=Decimal("14.0000"),
        risk_event_count=0,
        paper_sharpe=Decimal("1.0000"),
        live_sharpe=Decimal("0.8500"),
    )

    assert report.observation_count == 2
    assert report.direction_divergence_count == 1
    assert report.direction_divergence_rate == Decimal("0.5000")
    assert report.average_latency_delta_seconds == Decimal("2.5000")
    assert report.average_slippage_bps == Decimal("10.0000")
    assert report.sharpe_deviation == Decimal("0.1500")
    assert report.can_promote_capital is False


def test_paper_live_divergence_report_rejects_naive_datetimes() -> None:
    observation = ParallelRunObservation(
        signal_id="signal-1",
        signal_time=datetime(2026, 4, 30, 12, 0),
        paper_direction="BUY",
        live_direction="BUY",
        paper_order_time=datetime(2026, 4, 30, 12, 0, 1),
        live_order_time=datetime(2026, 4, 30, 12, 0, 2),
        paper_fill_price=Decimal("2300.00000000"),
        live_fill_price=Decimal("2300.00000000"),
    )

    try:
        build_paper_live_divergence_report([observation])
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive datetimes must be rejected")


def test_parallel_run_observation_persistence_is_decimal_safe_and_utc(db_session) -> None:
    signal_time = datetime(2026, 5, 1, 4, 0, tzinfo=UTC)

    observation = record_parallel_run_observation(
        db_session,
        signal_id="phase5-signal-1",
        symbol="XAUUSD",
        signal_time=signal_time,
        paper_direction="BUY",
        live_direction="BUY",
        paper_order_time=signal_time + timedelta(seconds=1),
        live_order_time=signal_time + timedelta(seconds=3),
        paper_fill_price=Decimal("2300.00000000"),
        live_fill_price=Decimal("2302.30000000"),
        order_notional=Decimal("230.00000000"),
        dry_run_status="accepted",
        guard_passed=True,
        risk_event_count=0,
        observed_at=signal_time + timedelta(seconds=4),
        metadata={"dry_run": True, "manual_approval_id": "phase5-12-approval"},
    )
    db_session.commit()

    persisted = db_session.execute(
        select(LiveParallelObservation).where(LiveParallelObservation.id == observation.id)
    ).scalar_one()

    assert persisted.signal_id == "phase5-signal-1"
    assert persisted.symbol == "XAUUSD"
    assert persisted.signal_time == signal_time
    assert persisted.signal_time.tzinfo is UTC
    assert persisted.paper_fill_price == Decimal("2300.00000000")
    assert persisted.live_fill_price == Decimal("2302.30000000")
    assert persisted.order_notional == Decimal("230.00000000")
    assert persisted.guard_passed is True
    assert persisted.risk_event_count == 0
    assert persisted.metadata_json == {"dry_run": True, "manual_approval_id": "phase5-12-approval"}


def test_parallel_run_observation_rejects_naive_datetimes(db_session) -> None:
    try:
        record_parallel_run_observation(
            db_session,
            signal_id="phase5-signal-2",
            symbol="XAUUSD",
            signal_time=datetime(2026, 5, 1, 4, 0),
            paper_direction="BUY",
            live_direction="BUY",
            paper_order_time=datetime(2026, 5, 1, 4, 0, 1, tzinfo=UTC),
            live_order_time=datetime(2026, 5, 1, 4, 0, 3, tzinfo=UTC),
            paper_fill_price=Decimal("2300.00000000"),
            live_fill_price=Decimal("2300.00000000"),
            order_notional=Decimal("230.00000000"),
            dry_run_status="accepted",
            guard_passed=True,
            risk_event_count=0,
            observed_at=datetime(2026, 5, 1, 4, 0, 4, tzinfo=UTC),
        )
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive parallel observation datetimes must be rejected")

    observations = db_session.execute(select(LiveParallelObservation)).scalars().all()
    assert observations == []


def test_persisted_parallel_run_report_builds_from_observation_rows(db_session) -> None:
    start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    record_parallel_run_observation(
        db_session,
        signal_id="phase5-signal-3",
        symbol="XAUUSD",
        signal_time=start,
        paper_direction="BUY",
        live_direction="BUY",
        paper_order_time=start + timedelta(seconds=1),
        live_order_time=start + timedelta(seconds=3),
        paper_fill_price=Decimal("2300.00000000"),
        live_fill_price=Decimal("2302.30000000"),
        order_notional=Decimal("230.00000000"),
        dry_run_status="accepted",
        guard_passed=True,
        risk_event_count=0,
        observed_at=start + timedelta(seconds=4),
    )
    record_parallel_run_observation(
        db_session,
        signal_id="phase5-signal-4",
        symbol="XAUUSD",
        signal_time=start + timedelta(days=14),
        paper_direction="BUY",
        live_direction="SELL",
        paper_order_time=start + timedelta(days=14, seconds=2),
        live_order_time=start + timedelta(days=14, seconds=5),
        paper_fill_price=Decimal("2300.00000000"),
        live_fill_price=Decimal("2297.70000000"),
        order_notional=Decimal("230.00000000"),
        dry_run_status="accepted",
        guard_passed=True,
        risk_event_count=1,
        observed_at=start + timedelta(days=14, seconds=6),
    )
    db_session.commit()

    report = build_persisted_parallel_run_report(
        db_session,
        paper_sharpe=Decimal("1.0000"),
        live_sharpe=Decimal("0.9000"),
    )

    assert report.observation_count == 2
    assert report.direction_divergence_count == 1
    assert report.direction_divergence_rate == Decimal("0.5000")
    assert report.average_latency_delta_seconds == Decimal("2.5000")
    assert report.average_slippage_bps == Decimal("10.0000")
    assert report.sharpe_deviation == Decimal("0.1000")
    assert report.running_days == Decimal("14.0000")
    assert report.risk_event_count == 1
    assert report.can_promote_capital is False


def test_gray_release_report_snapshot_includes_window_policy_and_blockers(db_session) -> None:
    start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    record_parallel_run_observation(
        db_session,
        signal_id="phase5-signal-5",
        symbol="XAUUSD",
        signal_time=start,
        paper_direction="BUY",
        live_direction="BUY",
        paper_order_time=start + timedelta(seconds=1),
        live_order_time=start + timedelta(seconds=2),
        paper_fill_price=Decimal("2300.00000000"),
        live_fill_price=Decimal("2300.00000000"),
        order_notional=Decimal("230.00000000"),
        dry_run_status="accepted",
        guard_passed=True,
        risk_event_count=0,
        observed_at=start + timedelta(seconds=3),
    )
    db_session.commit()

    snapshot = build_gray_release_report_snapshot(
        db_session,
        generated_at=start + timedelta(minutes=5),
        evidence_window_started=False,
        paper_sharpe=Decimal("1.0000"),
        live_sharpe=Decimal("0.9500"),
    )

    assert snapshot.generated_at == start + timedelta(minutes=5)
    assert snapshot.observation_count == 1
    assert snapshot.direction_divergence_rate == Decimal("0.0000")
    assert snapshot.average_slippage_bps == Decimal("0.0000")
    assert snapshot.sharpe_deviation == Decimal("0.0500")
    assert snapshot.evidence_window_started is False
    assert snapshot.can_promote_capital is False
    assert snapshot.acceptance_ready is False
    assert snapshot.acceptance_blockers == [
        "formal_evidence_window_not_started",
        "parallel_runtime_less_than_14_days",
    ]


def test_collect_parallel_run_observations_records_filled_paper_orders_once(db_session) -> None:
    signal_time = datetime(2026, 5, 1, 5, 0, tzinfo=UTC)
    strategy = _phase5_strategy()
    db_session.add(strategy)
    db_session.commit()
    signal = _phase5_signal(strategy, signal_time=signal_time)
    db_session.add(signal)
    db_session.commit()
    order = PaperOrder(
        signal_id=signal.id,
        symbol="XAUUSD",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.10000000"),
        price=Decimal("2300.00000000"),
        status="filled",
        filled_at=signal_time + timedelta(seconds=1),
    )
    db_session.add(order)
    db_session.commit()
    broker = CollectingDryRunBroker()

    result = collect_parallel_run_observations(
        db_session,
        broker=broker,
        as_of=signal_time + timedelta(seconds=5),
        total_equity=Decimal("100000.00000000"),
    )
    db_session.commit()

    observations = db_session.execute(select(LiveParallelObservation)).scalars().all()
    assert result.observed_count == 1
    assert result.skipped_count == 0
    assert result.as_of == signal_time + timedelta(seconds=5)
    assert len(observations) == 1
    assert observations[0].signal_id == str(signal.id)
    assert observations[0].paper_direction == "BUY"
    assert observations[0].live_direction == "BUY"
    assert observations[0].dry_run_status == "accepted"
    assert observations[0].guard_passed is True
    assert observations[0].order_notional == Decimal("230.00000000")
    assert observations[0].metadata_json["dry_run"] is True
    assert broker.requests[0][0].daily_notional_so_far == Decimal("0.00000000")
    assert broker.requests[0][1].manual_approval_id == f"phase5-observation-{order.id}"

    second_result = collect_parallel_run_observations(
        db_session,
        broker=broker,
        as_of=signal_time + timedelta(seconds=10),
        total_equity=Decimal("100000.00000000"),
    )
    db_session.commit()

    assert second_result.observed_count == 0
    assert second_result.skipped_count == 1
    assert db_session.execute(select(LiveParallelObservation)).scalars().all() == observations


def test_collect_parallel_run_observations_rejects_naive_as_of(db_session) -> None:
    try:
        collect_parallel_run_observations(
            db_session,
            broker=CollectingDryRunBroker(),
            as_of=datetime(2026, 5, 1, 5, 0),
            total_equity=Decimal("100000.00000000"),
        )
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive collection timestamps must be rejected")


def test_phase5_observation_collection_task_is_scheduled_disabled_by_default() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["collect-phase5-parallel-observations-every-5min"]["task"] == (
        "app.tasks.live.task_collect_parallel_observations"
    )
    assert schedule["collect-phase5-parallel-observations-every-5min"]["schedule"] == crontab(minute="*/5")
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"


def test_live_readiness_setting_change_appends_decimal_safe_audit_logs(db_session) -> None:
    changed_at = datetime(2026, 4, 30, 8, 0, tzinfo=UTC)

    first_log = record_live_readiness_setting_change(
        db_session,
        actor="phase5_admin",
        setting_name="daily_notional_limit",
        old_value=Decimal("0.00000000"),
        new_value=Decimal("5000.00000000"),
        reason="initial 1% gray release cap",
        changed_at=changed_at,
        ip_address="127.0.0.1",
    )
    second_log = record_live_readiness_setting_change(
        db_session,
        actor="phase5_admin",
        setting_name="kill_switch_enabled",
        old_value=True,
        new_value=False,
        reason="begin supervised paper/live parallel run",
        changed_at=changed_at + timedelta(minutes=1),
        ip_address="127.0.0.1",
    )
    db_session.commit()

    logs = db_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "live_readiness_setting_changed")
        .order_by(AuditLog.created_at.asc())
    ).scalars().all()

    assert [log.id for log in logs] == [first_log.id, second_log.id]
    assert logs[0].entity_type == "live_readiness"
    assert logs[0].actor == "phase5_admin"
    assert logs[0].ip_address == "127.0.0.1"
    assert logs[0].old_value == {"setting_name": "daily_notional_limit", "value": "0.00000000"}
    assert logs[0].new_value == {
        "setting_name": "daily_notional_limit",
        "value": "5000.00000000",
        "reason": "initial 1% gray release cap",
        "changed_at": "2026-04-30T08:00:00+00:00",
    }
    assert logs[1].new_value["setting_name"] == "kill_switch_enabled"
    assert logs[1].new_value["changed_at"] == "2026-04-30T08:01:00+00:00"


def test_live_readiness_setting_change_rejects_naive_datetime(db_session) -> None:
    try:
        record_live_readiness_setting_change(
            db_session,
            actor="phase5_admin",
            setting_name="manual_approval_required",
            old_value=True,
            new_value=True,
            reason="manual approval must remain forced",
            changed_at=datetime(2026, 4, 30, 8, 0),
        )
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive live readiness setting-change datetimes must be rejected")

    logs = db_session.execute(select(AuditLog)).scalars().all()
    assert logs == []


def test_live_broker_routing_is_disabled_by_default_after_readiness_passes() -> None:
    config = load_live_readiness_config(
        {
            "live": {
                "enabled": True,
                "kill_switch_enabled": False,
                "daily_notional_limit": "10000.00000000",
            }
        }
    )
    order_decision = evaluate_live_order_readiness(
        config,
        LiveOrderRequest(
            symbol="XAUUSD",
            side="BUY",
            quantity=Decimal("0.10000000"),
            price=Decimal("2300.00000000"),
            confidence=Decimal("0.9500"),
            daily_notional_so_far=Decimal("0.00000000"),
            total_equity=Decimal("100000.00000000"),
        ),
    )
    routing_request = LiveBrokerRoutingRequest(
        broker_name="mt5",
        credentials_configured=True,
        manual_approval_id="approval-1",
        approval_actor="phase5_admin",
        approved_at=datetime(2026, 4, 30, 8, 5, tzinfo=UTC),
    )

    routing_decision = evaluate_live_broker_routing(config, order_decision, routing_request)

    assert order_decision.passed is True
    assert routing_decision.passed is False
    assert routing_decision.reject_reason == "real_broker_routing_disabled"
    assert routing_decision.checks["real_broker_routing_enabled"] is False
    assert routing_decision.checks["broker_name"] == "mt5"


def test_live_broker_routing_requires_manual_approval_and_credentials() -> None:
    config = load_live_readiness_config(
        {
            "live": {
                "enabled": True,
                "kill_switch_enabled": False,
                "daily_notional_limit": "10000.00000000",
                "real_broker_routing_enabled": True,
            }
        }
    )
    order_decision = evaluate_live_order_readiness(
        config,
        LiveOrderRequest(
            symbol="XAUUSD",
            side="BUY",
            quantity=Decimal("0.10000000"),
            price=Decimal("2300.00000000"),
            confidence=Decimal("0.9500"),
            daily_notional_so_far=Decimal("0.00000000"),
            total_equity=Decimal("100000.00000000"),
        ),
    )

    missing_approval = evaluate_live_broker_routing(
        config,
        order_decision,
        LiveBrokerRoutingRequest(
            broker_name="ibkr",
            credentials_configured=True,
            manual_approval_id=None,
            approval_actor=None,
            approved_at=None,
        ),
    )
    missing_credentials = evaluate_live_broker_routing(
        config,
        order_decision,
        LiveBrokerRoutingRequest(
            broker_name="ibkr",
            credentials_configured=False,
            manual_approval_id="approval-2",
            approval_actor="phase5_admin",
            approved_at=datetime(2026, 4, 30, 8, 10, tzinfo=UTC),
        ),
    )

    assert missing_approval.passed is False
    assert missing_approval.reject_reason == "manual_approval_missing"
    assert missing_credentials.passed is False
    assert missing_credentials.reject_reason == "broker_credentials_missing"


def test_live_broker_routing_allows_only_fully_approved_guard_decision() -> None:
    config = load_live_readiness_config(
        {
            "live": {
                "enabled": True,
                "kill_switch_enabled": False,
                "daily_notional_limit": "10000.00000000",
                "real_broker_routing_enabled": True,
            }
        }
    )
    order_decision = evaluate_live_order_readiness(
        config,
        LiveOrderRequest(
            symbol="XAUUSD",
            side="BUY",
            quantity=Decimal("0.10000000"),
            price=Decimal("2300.00000000"),
            confidence=Decimal("0.9500"),
            daily_notional_so_far=Decimal("0.00000000"),
            total_equity=Decimal("100000.00000000"),
        ),
    )

    routing_decision = evaluate_live_broker_routing(
        config,
        order_decision,
        LiveBrokerRoutingRequest(
            broker_name="ibkr",
            credentials_configured=True,
            manual_approval_id="approval-3",
            approval_actor="phase5_admin",
            approved_at=datetime(2026, 4, 30, 8, 15, tzinfo=UTC),
        ),
    )

    assert routing_decision.passed is True
    assert routing_decision.reject_reason is None
    assert routing_decision.checks["approved_at"] == "2026-04-30T08:15:00+00:00"


def test_live_broker_routing_rejects_naive_approval_time() -> None:
    config = load_live_readiness_config(
        {
            "live": {
                "enabled": True,
                "kill_switch_enabled": False,
                "daily_notional_limit": "10000.00000000",
                "real_broker_routing_enabled": True,
            }
        }
    )
    order_decision = evaluate_live_order_readiness(
        config,
        LiveOrderRequest(
            symbol="XAUUSD",
            side="BUY",
            quantity=Decimal("0.10000000"),
            price=Decimal("2300.00000000"),
            confidence=Decimal("0.9500"),
            daily_notional_so_far=Decimal("0.00000000"),
            total_equity=Decimal("100000.00000000"),
        ),
    )

    try:
        evaluate_live_broker_routing(
            config,
            order_decision,
            LiveBrokerRoutingRequest(
                broker_name="ibkr",
                credentials_configured=True,
                manual_approval_id="approval-4",
                approval_actor="phase5_admin",
                approved_at=datetime(2026, 4, 30, 8, 20),
            ),
        )
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive live broker approval times must be rejected")
