from __future__ import annotations

import asyncio
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.database import get_session
from app.main import app
from app.models import AuditLog, RiskEvent
from app.services.live_readiness import record_parallel_run_observation


async def _request(db_session, json: dict[str, object]) -> httpx.Response:
    from app.routes.live import require_live_admin

    def override_db():
        yield db_session

    def override_admin():
        return SimpleNamespace(username="phase5_admin")

    app.dependency_overrides[get_session] = override_db
    app.dependency_overrides[require_live_admin] = override_admin
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post("/api/v1/live/emergency-stop", json=json)
    finally:
        app.dependency_overrides.clear()


async def _get_report(db_session, params: dict[str, object] | None = None) -> httpx.Response:
    from app.routes.live import require_live_admin

    def override_db():
        yield db_session

    def override_admin():
        return SimpleNamespace(username="phase5_admin")

    app.dependency_overrides[get_session] = override_db
    app.dependency_overrides[require_live_admin] = override_admin
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/api/v1/live/gray-release-report", params=params or {})
    finally:
        app.dependency_overrides.clear()


def test_live_emergency_stop_endpoint_appends_audit_and_risk_event(db_session) -> None:
    response = asyncio.run(
        _request(
            db_session,
            {
                "reason": "broker outage during supervised gray release",
                "requested_at": "2026-04-30T09:00:00+00:00",
                "open_live_position_ids": ["live-position-1", "live-position-2"],
            },
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["kill_switch_enabled"] is True
    assert payload["data"]["real_broker_routing_enabled"] is False
    assert payload["data"]["close_all_positions_requested"] is True
    assert payload["data"]["close_position_count"] == 2
    assert payload["data"]["requested_at"] == "2026-04-30T09:00:00Z"

    audit_log = db_session.execute(
        select(AuditLog).where(AuditLog.action == "live_emergency_stop_triggered")
    ).scalar_one()
    risk_event = db_session.execute(
        select(RiskEvent).where(RiskEvent.event_type == "live_emergency_stop")
    ).scalar_one()

    assert str(audit_log.id) == payload["data"]["audit_log_id"]
    assert str(risk_event.id) == payload["data"]["risk_event_id"]
    assert audit_log.actor == "phase5_admin"
    assert audit_log.entity_type == "live_readiness"
    assert audit_log.new_value["kill_switch_enabled"] is True
    assert audit_log.new_value["real_broker_routing_enabled"] is False
    assert audit_log.new_value["open_live_position_ids"] == ["live-position-1", "live-position-2"]
    assert risk_event.severity == "critical"
    assert risk_event.action_taken == "halt_trading_and_request_position_close"
    assert risk_event.metadata_json["requested_at"] == "2026-04-30T09:00:00+00:00"


def test_live_emergency_stop_endpoint_rejects_naive_requested_at(db_session) -> None:
    response = asyncio.run(
        _request(
            db_session,
            {
                "reason": "naive timestamp must not be accepted",
                "requested_at": "2026-04-30T09:00:00",
                "open_live_position_ids": [],
            },
        )
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert db_session.execute(select(AuditLog)).scalars().all() == []
    assert db_session.execute(select(RiskEvent)).scalars().all() == []


def test_gray_release_report_endpoint_returns_unified_envelope(db_session) -> None:
    start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    record_parallel_run_observation(
        db_session,
        signal_id="phase5-api-signal-1",
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

    response = asyncio.run(
        _get_report(
            db_session,
            {
                "start_at": "2026-05-01T00:00:00+00:00",
                "end_at": "2026-05-01T00:10:00+00:00",
                "paper_sharpe": "1.0000",
                "live_sharpe": "0.9500",
            },
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["observation_count"] == 1
    assert payload["data"]["direction_divergence_rate"] == "0.0000"
    assert payload["data"]["average_slippage_bps"] == "0.0000"
    assert payload["data"]["sharpe_deviation"] == "0.0500"
    assert payload["data"]["evidence_window_started"] is False
    assert payload["data"]["acceptance_ready"] is False
    assert payload["data"]["acceptance_blockers"] == [
        "formal_evidence_window_not_started",
        "parallel_runtime_less_than_14_days",
    ]


def test_gray_release_report_endpoint_rejects_naive_window_times(db_session) -> None:
    response = asyncio.run(_get_report(db_session, {"start_at": "2026-05-01T00:00:00"}))

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
