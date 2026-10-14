from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_viewer
from app.database import get_session
from app.schemas import ApiException, success_response
from app.services.core_api import ensure_utc_datetime
from app.services.paper_execution import get_paper_account, list_paper_orders, list_paper_positions
from app.services.risk_engine import get_risk_status, list_risk_events


router = APIRouter(tags=["paper"])


def _validate_date_range(start_date: datetime | None, end_date: datetime | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ApiException(
            status_code=400,
            code="VALIDATION_ERROR",
            message="start_date must be earlier than or equal to end_date.",
            detail={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        )


@router.get("/paper/orders", dependencies=[Depends(require_viewer)])
def read_paper_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    session: Session = Depends(get_session),
):
    return success_response(list_paper_orders(session, page=page, page_size=page_size, status_value=status))


@router.get("/paper/positions", dependencies=[Depends(require_viewer)])
def read_paper_positions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    session: Session = Depends(get_session),
):
    return success_response(list_paper_positions(session, page=page, page_size=page_size, status_value=status))


@router.get("/paper/account", dependencies=[Depends(require_viewer)])
def read_paper_account(session: Session = Depends(get_session)):
    return success_response(get_paper_account(session))


@router.get("/risk/events", dependencies=[Depends(require_viewer)])
def read_risk_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    severity: str | None = None,
    event_type: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    session: Session = Depends(get_session),
):
    start_date = ensure_utc_datetime(start_date, "start_date")
    end_date = ensure_utc_datetime(end_date, "end_date")
    _validate_date_range(start_date, end_date)
    return success_response(
        list_risk_events(
            session,
            page=page,
            page_size=page_size,
            severity=severity,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
        )
    )


@router.get("/risk/status", dependencies=[Depends(require_viewer)])
def read_risk_status(session: Session = Depends(get_session)):
    return success_response(get_risk_status(session))
