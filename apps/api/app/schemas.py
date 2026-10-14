from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar
from uuid import UUID

from fastapi import status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


T = TypeVar("T")


class ErrorPayload(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] | list[dict[str, Any]] | None = None


class ApiEnvelope(BaseModel, Generic[T]):
    success: bool
    data: T | None
    error: ErrorPayload | None = None


class ApiException(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        detail: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


class HealthData(BaseModel):
    status: str
    version: str
    db_connected: bool
    redis_connected: bool
    timestamp: str = Field(description="UTC ISO 8601 timestamp")


class HealthEnvelope(ApiEnvelope[HealthData]):
    data: HealthData


class NewsSentimentSummary(BaseModel):
    label: str
    score: Decimal


class SentimentScoreData(BaseModel):
    id: UUID
    analyzer_type: str
    sentiment: str
    score: Decimal
    confidence: Decimal
    reasoning: str | None
    metadata: dict[str, Any]
    created_at: datetime


class EventTagData(BaseModel):
    id: UUID
    tag_type: str
    tag_value: str
    relevance_score: Decimal
    metadata: dict[str, Any]
    created_at: datetime


class NewsListItemData(BaseModel):
    id: UUID
    title: str
    summary: str | None
    source_id: UUID | None
    source_name: str | None
    published_at: datetime
    status: str
    sentiment: NewsSentimentSummary | None
    event_tags: list[str]


class NewsDetailData(BaseModel):
    id: UUID
    source_id: UUID | None
    source_name: str | None
    title: str
    summary: str | None
    content: str | None
    url: str | None
    author: str | None
    published_at: datetime
    fetched_at: datetime
    language: str
    status: str
    raw_data: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    sentiment_scores: list[SentimentScoreData]
    event_tags: list[EventTagData]


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class SentimentAggregateData(BaseModel):
    window: str
    avg_score: Decimal | None
    positive_count: int
    negative_count: int
    neutral_count: int
    dominant_events: list[str]
    calculated_at: datetime


class EventListItemData(BaseModel):
    id: UUID
    news_id: UUID
    tag_type: str
    tag_value: str
    relevance_score: Decimal
    metadata: dict[str, Any]
    created_at: datetime
    news_title: str
    published_at: datetime


class SignalListItemData(BaseModel):
    id: UUID
    strategy_run_id: UUID
    strategy_name: str
    symbol: str
    signal_time: datetime
    direction: str
    strength: Decimal
    confidence: Decimal
    price_at_signal: Decimal | None
    reasoning: str
    source_type: str
    created_at: datetime


class BacktestCreateRequest(BaseModel):
    strategy_run_id: UUID
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(gt=0, decimal_places=2, max_digits=20)
    slippage_bps: int = Field(default=0, ge=0, le=10000)
    commission_bps: int = Field(default=0, ge=0, le=10000)


class BacktestCreateResponseData(BaseModel):
    backtest_id: UUID
    status: str
    message: str


class BacktestTradeLogItemData(BaseModel):
    side: str
    entry_time: datetime
    exit_time: datetime
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    commission: Decimal
    slippage_bps: int


class BacktestListItemData(BaseModel):
    id: UUID
    strategy_run_id: UUID
    strategy_name: str
    start_date: date
    end_date: date
    status: str
    initial_capital: Decimal
    final_capital: Decimal | None
    total_return: Decimal | None
    max_drawdown: Decimal | None
    sharpe_ratio: Decimal | None
    win_rate: Decimal | None
    total_trades: int
    created_at: datetime
    completed_at: datetime | None


class BacktestDetailData(BacktestListItemData):
    error_message: str | None
    equity_curve: list[tuple[datetime, Decimal]]
    trade_log: list[BacktestTradeLogItemData]


class PaperOrderData(BaseModel):
    id: UUID
    signal_id: UUID
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    price: Decimal | None
    limit_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    slippage: Decimal
    commission: Decimal
    status: str
    reject_reason: str | None
    filled_at: datetime | None
    created_at: datetime


class PaperPositionData(BaseModel):
    id: UUID
    symbol: str
    side: str
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    trailing_stop_distance: Decimal | None
    trailing_stop_price: Decimal | None
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    status: str
    opened_at: datetime
    closed_at: datetime | None
    entry_order_id: UUID | None
    exit_order_id: UUID | None
    created_at: datetime
    updated_at: datetime


class PaperAccountData(BaseModel):
    total_equity: Decimal
    cash: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    open_positions: int
    today_pnl: Decimal


class RiskEventData(BaseModel):
    id: UUID
    event_type: str
    severity: str
    trigger_value: Decimal | None
    threshold_value: Decimal | None
    action_taken: str
    related_order_id: UUID | None
    description: str | None
    metadata: dict[str, Any]
    created_at: datetime


class RiskStatusEventSummary(BaseModel):
    type: str
    time: datetime


class RiskStatusData(BaseModel):
    trading_enabled: bool
    current_drawdown: Decimal
    max_drawdown_limit: Decimal
    position_count: int
    position_limit: int
    circuit_breaker_active: bool
    last_risk_event: RiskStatusEventSummary | None


class LiveEmergencyStopRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    requested_at: datetime | None = None
    open_live_position_ids: list[str] = Field(default_factory=list, max_length=100)


class LiveEmergencyStopResultData(BaseModel):
    kill_switch_enabled: bool
    real_broker_routing_enabled: bool
    close_all_positions_requested: bool
    close_position_count: int
    audit_log_id: UUID
    risk_event_id: UUID
    requested_at: datetime


class GrayReleaseReportData(BaseModel):
    generated_at: datetime
    observation_count: int
    direction_divergence_count: int
    direction_divergence_rate: Decimal
    average_latency_delta_seconds: Decimal
    average_slippage_bps: Decimal
    sharpe_deviation: Decimal
    running_days: Decimal
    risk_event_count: int
    can_promote_capital: bool
    evidence_window_started: bool
    acceptance_ready: bool
    acceptance_blockers: list[str]


def success_response(data: BaseModel, status_code: int = status.HTTP_200_OK) -> JSONResponse:
    body = ApiEnvelope[Any](success=True, data=data, error=None)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    detail: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body = ApiEnvelope[Any](
        success=False,
        data=None,
        error=ErrorPayload(code=code, message=message, detail=detail),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))
