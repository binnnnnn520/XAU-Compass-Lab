from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_viewer
from app.database import get_session
from app.schemas import ApiException, success_response
from app.services.core_api import (
    NewsStatus,
    SentimentLabel,
    SentimentWindow,
    SignalDirection,
    SignalSourceType,
    ensure_utc_datetime,
    get_news_detail,
    get_sentiment_aggregate,
    list_events,
    list_news,
    list_signals,
)


router = APIRouter(tags=["core-api"])

CanonicalSymbol = Literal["XAUUSD"]
EventTagType = Literal["geopolitical", "monetary_policy", "economic_data", "crisis"]


def _validate_date_range(start_date: datetime | None, end_date: datetime | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ApiException(
            status_code=400,
            code="VALIDATION_ERROR",
            message="start_date must be earlier than or equal to end_date.",
            detail={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        )


@router.get("/news", dependencies=[Depends(require_viewer)])
def read_news(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source_id: UUID | None = None,
    status: NewsStatus | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    sentiment: SentimentLabel | None = None,
    session: Session = Depends(get_session),
):
    start_date = ensure_utc_datetime(start_date, "start_date")
    end_date = ensure_utc_datetime(end_date, "end_date")
    _validate_date_range(start_date, end_date)
    data = list_news(
        session,
        page=page,
        page_size=page_size,
        source_id=source_id,
        status_value=status,
        start_date=start_date,
        end_date=end_date,
        sentiment=sentiment,
    )
    return success_response(data)


@router.get("/news/{news_id}", dependencies=[Depends(require_viewer)])
def read_news_detail(news_id: UUID, session: Session = Depends(get_session)):
    return success_response(get_news_detail(session, news_id))


@router.get("/sentiment/aggregate", dependencies=[Depends(require_viewer)])
def read_sentiment_aggregate(
    window: SentimentWindow = "4h",
    symbol: CanonicalSymbol = Query(default="XAUUSD"),
    session: Session = Depends(get_session),
):
    return success_response(get_sentiment_aggregate(session, window=window))


@router.get("/events", dependencies=[Depends(require_viewer)])
def read_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tag_type: EventTagType | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    session: Session = Depends(get_session),
):
    start_date = ensure_utc_datetime(start_date, "start_date")
    end_date = ensure_utc_datetime(end_date, "end_date")
    _validate_date_range(start_date, end_date)
    data = list_events(
        session,
        page=page,
        page_size=page_size,
        tag_type=tag_type,
        start_date=start_date,
        end_date=end_date,
    )
    return success_response(data)


@router.get("/signals", dependencies=[Depends(require_viewer)])
def read_signals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    direction: SignalDirection | None = None,
    strategy_run_id: UUID | None = None,
    source_type: SignalSourceType | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_confidence: Decimal | None = Query(default=None, ge=0, le=1),
    session: Session = Depends(get_session),
):
    start_date = ensure_utc_datetime(start_date, "start_date")
    end_date = ensure_utc_datetime(end_date, "end_date")
    _validate_date_range(start_date, end_date)
    data = list_signals(
        session,
        page=page,
        page_size=page_size,
        direction=direction,
        strategy_run_id=strategy_run_id,
        source_type=source_type,
        start_date=start_date,
        end_date=end_date,
        min_confidence=min_confidence,
    )
    return success_response(data)
