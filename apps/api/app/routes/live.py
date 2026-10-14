from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.auth.models import User
from app.config import get_settings
from app.database import get_session
from app.schemas import GrayReleaseReportData, LiveEmergencyStopRequest, LiveEmergencyStopResultData, success_response
from app.services.core_api import ensure_utc_datetime
from app.services.live_readiness import build_gray_release_report_snapshot, trigger_live_emergency_stop


router = APIRouter(tags=["live"])
require_live_admin = require_roles("admin")


@router.post("/live/emergency-stop")
def trigger_emergency_stop(
    payload: LiveEmergencyStopRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_live_admin),
):
    requested_at = ensure_utc_datetime(payload.requested_at or datetime.now(UTC), "requested_at")
    result = trigger_live_emergency_stop(
        session,
        actor=current_user.username,
        reason=payload.reason,
        requested_at=requested_at,
        open_live_position_ids=payload.open_live_position_ids,
        ip_address=request.client.host if request.client is not None else None,
    )
    session.commit()
    return success_response(
        LiveEmergencyStopResultData(
            kill_switch_enabled=result.kill_switch_enabled,
            real_broker_routing_enabled=result.real_broker_routing_enabled,
            close_all_positions_requested=result.close_all_positions_requested,
            close_position_count=result.close_position_count,
            audit_log_id=result.audit_log_id,
            risk_event_id=result.risk_event_id,
            requested_at=result.requested_at,
        )
    )


@router.get("/live/gray-release-report")
def get_gray_release_report(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    paper_sharpe: Decimal = Query(default=Decimal("0.0000")),
    live_sharpe: Decimal = Query(default=Decimal("0.0000")),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_live_admin),
):
    del current_user
    snapshot = build_gray_release_report_snapshot(
        session,
        generated_at=datetime.now(UTC),
        evidence_window_started=get_settings().phase5_evidence_window_started,
        start_at=ensure_utc_datetime(start_at, "start_at"),
        end_at=ensure_utc_datetime(end_at, "end_at"),
        paper_sharpe=paper_sharpe,
        live_sharpe=live_sharpe,
    )
    return success_response(
        GrayReleaseReportData(
            generated_at=snapshot.generated_at,
            observation_count=snapshot.observation_count,
            direction_divergence_count=snapshot.direction_divergence_count,
            direction_divergence_rate=snapshot.direction_divergence_rate,
            average_latency_delta_seconds=snapshot.average_latency_delta_seconds,
            average_slippage_bps=snapshot.average_slippage_bps,
            sharpe_deviation=snapshot.sharpe_deviation,
            running_days=snapshot.running_days,
            risk_event_count=snapshot.risk_event_count,
            can_promote_capital=snapshot.can_promote_capital,
            evidence_window_started=snapshot.evidence_window_started,
            acceptance_ready=snapshot.acceptance_ready,
            acceptance_blockers=snapshot.acceptance_blockers,
        )
    )
