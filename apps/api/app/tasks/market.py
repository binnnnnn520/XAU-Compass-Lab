from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal, get_engine
from app.models import MarketBar
from app.services.price_feed import build_price_message
from app.services.price_feed.pubsub import RedisRealtimePublisher
from app.services.market_ingestion import sync_bars_with_details


class PricePublisher(Protocol):
    def publish(self, message: dict[str, Any]) -> int:
        ...


def _parse_task_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _default_window(lookback_hours: int) -> tuple[datetime, datetime]:
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=lookback_hours)
    return start, end


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _publish_latest_price(
    session,
    *,
    symbol: str,
    timeframe: str,
    as_of: datetime,
    publisher: PricePublisher | None = None,
) -> bool:
    latest_bar = session.execute(
        select(MarketBar)
        .where(
            MarketBar.symbol == symbol,
            MarketBar.timeframe == timeframe,
            MarketBar.bar_time <= _utc(as_of),
        )
        .order_by(MarketBar.bar_time.desc())
        .limit(1)
    ).scalar_one_or_none()

    if latest_bar is None:
        return False

    active_publisher = publisher or RedisRealtimePublisher()
    active_publisher.publish(
        build_price_message(
            symbol=latest_bar.symbol,
            timeframe=latest_bar.timeframe,
            price=latest_bar.close,
            as_of=_utc(latest_bar.bar_time),
        )
    )
    return True


@celery_app.task(name="app.tasks.market.task_sync_market_bars")
def task_sync_market_bars(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "1h",
    lookback_hours: int | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    explicit_start = _parse_task_datetime(start_iso)
    explicit_end = _parse_task_datetime(end_iso)
    if explicit_start is None or explicit_end is None:
        start, end = _default_window(lookback_hours or settings.market_sync_lookback_hours)
    else:
        start, end = explicit_start, explicit_end

    engine = get_engine()
    session_factory = SessionLocal
    session_factory.configure(bind=engine)
    session = session_factory()
    try:
        summary = sync_bars_with_details(
            session,
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            settings=settings,
        )
        price_published = _publish_latest_price(session, symbol=symbol, timeframe=timeframe, as_of=end)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "bars_seen": summary.bars_seen,
            "bars_inserted": summary.bars_inserted,
            "bars_skipped": summary.bars_skipped,
            "gap_count": summary.gap_count,
            "gaps": [gap.isoformat() for gap in summary.gaps],
            "price_published": price_published,
        }
    finally:
        session.close()
        engine.dispose()
