from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_trader, require_viewer
from app.auth.models import User
from app.database import get_session
from app.schemas import BacktestCreateRequest, success_response
from app.services.backtest_engine import create_and_run_backtest, get_backtest, list_backtests


router = APIRouter(tags=["backtest"])

BacktestStatus = Literal["pending", "running", "completed", "failed"]


@router.post("/backtest")
def create_backtest(
    payload: BacktestCreateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_trader),
):
    return success_response(create_and_run_backtest(session, payload))


@router.get("/backtest/{backtest_id}", dependencies=[Depends(require_viewer)])
def read_backtest(backtest_id: UUID, session: Session = Depends(get_session)):
    return success_response(get_backtest(session, backtest_id))


@router.get("/backtest", dependencies=[Depends(require_viewer)])
def read_backtests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    strategy_run_id: UUID | None = None,
    status: BacktestStatus | None = None,
    session: Session = Depends(get_session),
):
    return success_response(
        list_backtests(
            session,
            page=page,
            page_size=page_size,
            strategy_run_id=strategy_run_id,
            status_value=status,
        )
    )
