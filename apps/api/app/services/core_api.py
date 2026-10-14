from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.database import utcnow
from app.models import EventTag, NewsItem, SentimentScore, Signal
from app.schemas import (
    ApiException,
    EventListItemData,
    EventTagData,
    NewsDetailData,
    NewsListItemData,
    NewsSentimentSummary,
    PaginatedData,
    SentimentAggregateData,
    SentimentScoreData,
    SignalListItemData,
)


NewsStatus = Literal["pending", "analyzed", "failed"]
SentimentLabel = Literal["positive", "negative", "neutral"]
SignalDirection = Literal["BUY", "SELL", "HOLD"]
SignalSourceType = Literal["live", "backtest"]
SentimentWindow = Literal["1h", "4h", "1d", "7d"]

WINDOW_TO_DELTA: dict[SentimentWindow, timedelta] = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
}


def ensure_utc_datetime(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ApiException(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message=f"{field_name} must be a UTC-aware datetime.",
            detail={"field": field_name},
        )
    return value.astimezone(UTC)


def _quantize(value: Decimal | None, precision: str = "0.0000") -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal(precision))


def _serialize_sentiment(score: SentimentScore | None) -> NewsSentimentSummary | None:
    if score is None:
        return None
    return NewsSentimentSummary(label=score.sentiment, score=score.score)


def _serialize_sentiment_score(score: SentimentScore) -> SentimentScoreData:
    return SentimentScoreData(
        id=score.id,
        analyzer_type=score.analyzer_type,
        sentiment=score.sentiment,
        score=score.score,
        confidence=score.confidence,
        reasoning=score.reasoning,
        metadata=score.metadata_json,
        created_at=score.created_at,
    )


def _serialize_event_tag(tag: EventTag) -> EventTagData:
    return EventTagData(
        id=tag.id,
        tag_type=tag.tag_type,
        tag_value=tag.tag_value,
        relevance_score=tag.relevance_score,
        metadata=tag.metadata_json,
        created_at=tag.created_at,
    )


def _serialize_news_item(item: NewsItem) -> NewsListItemData:
    sentiment = max(item.sentiment_scores, key=lambda score: score.created_at, default=None)
    event_tags = sorted({tag.tag_value for tag in item.event_tags})
    source_name = item.source.name if item.source is not None else None
    return NewsListItemData(
        id=item.id,
        title=item.title,
        summary=item.summary,
        source_id=item.source_id,
        source_name=source_name,
        published_at=item.published_at,
        status=item.status,
        sentiment=_serialize_sentiment(sentiment),
        event_tags=event_tags,
    )


def _serialize_news_detail(item: NewsItem) -> NewsDetailData:
    source_name = item.source.name if item.source is not None else None
    sentiments = sorted(item.sentiment_scores, key=lambda score: score.created_at, reverse=True)
    event_tags = sorted(item.event_tags, key=lambda tag: tag.created_at, reverse=True)
    return NewsDetailData(
        id=item.id,
        source_id=item.source_id,
        source_name=source_name,
        title=item.title,
        summary=item.summary,
        content=item.content,
        url=item.url,
        author=item.author,
        published_at=item.published_at,
        fetched_at=item.fetched_at,
        language=item.language,
        status=item.status,
        raw_data=item.raw_data,
        created_at=item.created_at,
        updated_at=item.updated_at,
        sentiment_scores=[_serialize_sentiment_score(score) for score in sentiments],
        event_tags=[_serialize_event_tag(tag) for tag in event_tags],
    )


def _news_row_query(
    *,
    source_id: UUID | None,
    status_value: NewsStatus | None,
    start_date: datetime | None,
    end_date: datetime | None,
    sentiment: SentimentLabel | None,
):
    stmt = select(NewsItem.id.label("id"), NewsItem.published_at.label("published_at")).select_from(NewsItem)
    if sentiment is not None:
        stmt = stmt.join(SentimentScore, SentimentScore.news_id == NewsItem.id)
        stmt = stmt.where(SentimentScore.sentiment == sentiment)
    if source_id is not None:
        stmt = stmt.where(NewsItem.source_id == source_id)
    if status_value is not None:
        stmt = stmt.where(NewsItem.status == status_value)
    if start_date is not None:
        stmt = stmt.where(NewsItem.published_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(NewsItem.published_at <= end_date)
    return stmt.group_by(NewsItem.id, NewsItem.published_at)


def list_news(
    session: Session,
    *,
    page: int,
    page_size: int,
    source_id: UUID | None,
    status_value: NewsStatus | None,
    start_date: datetime | None,
    end_date: datetime | None,
    sentiment: SentimentLabel | None,
) -> PaginatedData[NewsListItemData]:
    row_query = _news_row_query(
        source_id=source_id,
        status_value=status_value,
        start_date=start_date,
        end_date=end_date,
        sentiment=sentiment,
    )
    total = session.execute(select(func.count()).select_from(row_query.subquery())).scalar_one()
    rows = session.execute(
        row_query.order_by(NewsItem.published_at.desc(), NewsItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    ids = [row.id for row in rows]
    if not ids:
        return PaginatedData[NewsListItemData](items=[], total=total, page=page, page_size=page_size)

    items = session.execute(
        select(NewsItem)
        .options(
            selectinload(NewsItem.source),
            selectinload(NewsItem.sentiment_scores),
            selectinload(NewsItem.event_tags),
        )
        .where(NewsItem.id.in_(ids))
    ).scalars().all()
    items_by_id = {item.id: item for item in items}

    return PaginatedData[NewsListItemData](
        items=[_serialize_news_item(items_by_id[item_id]) for item_id in ids],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_news_detail(session: Session, news_id: UUID) -> NewsDetailData:
    item = session.execute(
        select(NewsItem)
        .options(
            selectinload(NewsItem.source),
            selectinload(NewsItem.sentiment_scores),
            selectinload(NewsItem.event_tags),
        )
        .where(NewsItem.id == news_id)
    ).scalar_one_or_none()
    if item is None:
        raise ApiException(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="News item not found.",
            detail={"news_id": str(news_id)},
        )
    return _serialize_news_detail(item)


def get_sentiment_aggregate(
    session: Session,
    *,
    window: SentimentWindow,
) -> SentimentAggregateData:
    calculated_at = utcnow()
    start_time = calculated_at - WINDOW_TO_DELTA[window]

    counts = session.execute(
        select(
            func.avg(SentimentScore.score),
            func.count(case((SentimentScore.sentiment == "positive", 1))),
            func.count(case((SentimentScore.sentiment == "negative", 1))),
            func.count(case((SentimentScore.sentiment == "neutral", 1))),
        )
        .join(NewsItem, NewsItem.id == SentimentScore.news_id)
        .where(NewsItem.published_at >= start_time, NewsItem.published_at <= calculated_at)
    ).one()

    dominant_events = session.execute(
        select(EventTag.tag_value, func.count(EventTag.id).label("tag_count"))
        .join(NewsItem, NewsItem.id == EventTag.news_id)
        .where(NewsItem.published_at >= start_time, NewsItem.published_at <= calculated_at)
        .group_by(EventTag.tag_value)
        .order_by(func.count(EventTag.id).desc(), EventTag.tag_value.asc())
        .limit(5)
    ).all()

    return SentimentAggregateData(
        window=window,
        avg_score=_quantize(counts[0]) or Decimal("0.0000"),
        positive_count=counts[1] or 0,
        negative_count=counts[2] or 0,
        neutral_count=counts[3] or 0,
        dominant_events=[row.tag_value for row in dominant_events],
        calculated_at=calculated_at,
    )


def list_events(
    session: Session,
    *,
    page: int,
    page_size: int,
    tag_type: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
) -> PaginatedData[EventListItemData]:
    row_query = (
        select(
            EventTag.id.label("id"),
            NewsItem.published_at.label("published_at"),
            EventTag.created_at.label("created_at"),
        )
        .select_from(EventTag)
        .join(NewsItem, NewsItem.id == EventTag.news_id)
    )
    if tag_type is not None:
        row_query = row_query.where(EventTag.tag_type == tag_type)
    if start_date is not None:
        row_query = row_query.where(NewsItem.published_at >= start_date)
    if end_date is not None:
        row_query = row_query.where(NewsItem.published_at <= end_date)
    row_query = row_query.group_by(EventTag.id, NewsItem.published_at, EventTag.created_at)

    total = session.execute(select(func.count()).select_from(row_query.subquery())).scalar_one()
    rows = session.execute(
        row_query.order_by(EventTag.created_at.desc(), EventTag.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    ids = [row.id for row in rows]
    if not ids:
        return PaginatedData[EventListItemData](items=[], total=total, page=page, page_size=page_size)

    tags = session.execute(
        select(EventTag)
        .options(selectinload(EventTag.news_item).selectinload(NewsItem.source))
        .where(EventTag.id.in_(ids))
    ).scalars().all()
    tags_by_id = {tag.id: tag for tag in tags}

    items = []
    for tag_id in ids:
        tag = tags_by_id[tag_id]
        items.append(
            EventListItemData(
                id=tag.id,
                news_id=tag.news_id,
                tag_type=tag.tag_type,
                tag_value=tag.tag_value,
                relevance_score=tag.relevance_score,
                metadata=tag.metadata_json,
                created_at=tag.created_at,
                news_title=tag.news_item.title,
                published_at=tag.news_item.published_at,
            )
        )

    return PaginatedData[EventListItemData](items=items, total=total, page=page, page_size=page_size)


def list_signals(
    session: Session,
    *,
    page: int,
    page_size: int,
    direction: SignalDirection | None,
    strategy_run_id: UUID | None,
    source_type: SignalSourceType | None,
    start_date: datetime | None,
    end_date: datetime | None,
    min_confidence: Decimal | None,
) -> PaginatedData[SignalListItemData]:
    row_query = select(Signal.id.label("id"), Signal.signal_time.label("signal_time")).select_from(Signal)
    if direction is not None:
        row_query = row_query.where(Signal.direction == direction)
    if strategy_run_id is not None:
        row_query = row_query.where(Signal.strategy_run_id == strategy_run_id)
    if source_type is not None:
        row_query = row_query.where(Signal.source_type == source_type)
    if start_date is not None:
        row_query = row_query.where(Signal.signal_time >= start_date)
    if end_date is not None:
        row_query = row_query.where(Signal.signal_time <= end_date)
    if min_confidence is not None:
        row_query = row_query.where(Signal.confidence >= min_confidence)
    row_query = row_query.group_by(Signal.id, Signal.signal_time)

    total = session.execute(select(func.count()).select_from(row_query.subquery())).scalar_one()
    rows = session.execute(
        row_query.order_by(Signal.signal_time.desc(), Signal.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    ids = [row.id for row in rows]
    if not ids:
        return PaginatedData[SignalListItemData](items=[], total=total, page=page, page_size=page_size)

    signals = session.execute(
        select(Signal)
        .options(selectinload(Signal.strategy_run))
        .where(Signal.id.in_(ids))
    ).scalars().all()
    signals_by_id = {signal.id: signal for signal in signals}

    items = []
    for signal_id in ids:
        signal = signals_by_id[signal_id]
        strategy = signal.strategy_run
        items.append(
            SignalListItemData(
                id=signal.id,
                strategy_run_id=signal.strategy_run_id,
                strategy_name=strategy.strategy_name,
                symbol=signal.symbol,
                signal_time=signal.signal_time,
                direction=signal.direction,
                strength=signal.strength,
                confidence=signal.confidence,
                price_at_signal=signal.price_at_signal,
                reasoning=signal.reasoning,
                source_type=signal.source_type,
                created_at=signal.created_at,
            )
        )

    return PaginatedData[SignalListItemData](items=items, total=total, page=page, page_size=page_size)
