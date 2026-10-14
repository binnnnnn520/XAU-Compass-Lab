from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import hashlib
from time import struct_time
from typing import Any, Callable

import feedparser
import httpx
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import NewsItem, NewsSource

MAX_FETCH_ATTEMPTS = 3
UNHEALTHY_PROBE_INTERVAL = 3600


@dataclass(frozen=True)
class FeedEntry:
    title: str
    content: str | None
    summary: str | None
    url: str | None
    author: str | None
    published_at: datetime
    language: str
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class IngestionSummary:
    sources_seen: int
    sources_processed: int
    sources_succeeded: int
    sources_failed: int
    items_created: int
    items_skipped: int


def _coerce_datetime(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    if isinstance(value, str) and value.strip():
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)

    if isinstance(value, struct_time):
        return datetime(*value[:6], tzinfo=UTC)

    return fallback


def _entry_content(entry: feedparser.FeedParserDict) -> str | None:
    if entry.get("content"):
        first = entry["content"][0]
        if isinstance(first, dict):
            return first.get("value")
    return entry.get("description") or entry.get("summary")


def _entry_raw_data(entry: feedparser.FeedParserDict) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for key, value in entry.items():
        if isinstance(value, struct_time):
            raw[key] = datetime(*value[:6], tzinfo=UTC).isoformat()
        elif isinstance(value, list):
            raw[key] = value
        elif isinstance(value, dict):
            raw[key] = value
        elif value is None or isinstance(value, (str, int, float, bool)):
            raw[key] = value
        else:
            raw[key] = str(value)
    return raw


def parse_feed_entries(feed_content: str, fetched_at: datetime | None = None) -> list[FeedEntry]:
    normalized_fetched_at = fetched_at or datetime.now(UTC)
    parsed = feedparser.parse(feed_content)
    entries: list[FeedEntry] = []

    for entry in parsed.entries:
        title = str(entry.get("title", "")).strip()
        if not title:
            continue

        published_at = _coerce_datetime(
            entry.get("published_parsed") or entry.get("published") or entry.get("updated_parsed") or entry.get("updated"),
            normalized_fetched_at,
        )
        entries.append(
            FeedEntry(
                title=title,
                content=_entry_content(entry),
                summary=entry.get("summary"),
                url=entry.get("link"),
                author=entry.get("author"),
                published_at=published_at,
                language=str(entry.get("language") or parsed.feed.get("language") or "en"),
                raw_data=_entry_raw_data(entry),
            )
        )

    return entries


# Many RSS endpoints reject requests without a browser-like User-Agent.
NEWS_FEED_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)


def fetch_feed_content(url: str, timeout_seconds: float) -> str:
    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": NEWS_FEED_USER_AGENT},
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def title_hash(title: str) -> str:
    return hashlib.sha256(title.strip().encode("utf-8")).hexdigest()


def _eligible_sources_statement(now: datetime, only_unhealthy: bool) -> Select[tuple[NewsSource]]:
    statement = select(NewsSource).where(NewsSource.is_active.is_(True))
    if only_unhealthy:
        statement = statement.where(NewsSource.health_status == "unhealthy")
    else:
        statement = statement.where(NewsSource.health_status != "unhealthy")
    return statement.order_by(NewsSource.created_at.asc())


def _source_is_due(source: NewsSource, now: datetime, only_unhealthy: bool) -> bool:
    interval_seconds = UNHEALTHY_PROBE_INTERVAL if only_unhealthy else source.fetch_interval
    if source.last_fetched_at is None:
        return True
    return source.last_fetched_at + timedelta(seconds=interval_seconds) <= now


def _ensure_default_sources(session: Session, settings: Settings) -> None:
    if not settings.default_news_sources:
        return

    existing = {
        (source.name, source.url): source
        for source in session.execute(select(NewsSource)).scalars().all()
    }
    if existing:
        return

    for source_data in settings.default_news_sources:
        key = (str(source_data["name"]), str(source_data["url"]))
        if key in existing:
            continue
        session.add(
            NewsSource(
                name=key[0],
                url=key[1],
                source_type=str(source_data["source_type"]),
                fetch_interval=int(source_data["fetch_interval"]),
                config=source_data.get("config", {}) if isinstance(source_data.get("config"), dict) else {},
            )
        )
    session.commit()


def _mark_source_success(source: NewsSource, fetched_at: datetime) -> None:
    config = dict(source.config or {})
    config["consecutive_failures"] = 0
    config.pop("last_error", None)
    source.config = config
    source.health_status = "healthy"
    source.last_fetched_at = fetched_at


def _mark_source_failure(source: NewsSource, fetched_at: datetime, error_message: str, unhealthy: bool) -> None:
    config = dict(source.config or {})
    prior_failures = int(config.get("consecutive_failures", 0))
    config["consecutive_failures"] = prior_failures + 1
    config["last_error"] = error_message
    config["last_failure_at"] = fetched_at.isoformat()
    source.config = config
    source.last_fetched_at = fetched_at
    if unhealthy:
        source.health_status = "unhealthy"


def _persist_entries(session: Session, source: NewsSource, entries: list[FeedEntry], fetched_at: datetime) -> tuple[int, int]:
    created = 0
    skipped = 0

    for entry in entries:
        existing = session.execute(
            select(NewsItem.id).where(
                NewsItem.source_id == source.id,
                NewsItem.title_hash == title_hash(entry.title),
            )
        ).scalar_one_or_none()
        if existing is not None:
            skipped += 1
            continue

        item = NewsItem(
            source_id=source.id,
            title=entry.title,
            content=entry.content,
            summary=entry.summary,
            url=entry.url,
            author=entry.author,
            published_at=entry.published_at,
            fetched_at=fetched_at,
            title_hash=title_hash(entry.title),
            language=entry.language[:10] or "en",
            raw_data=entry.raw_data,
        )
        try:
            with session.begin_nested():
                session.add(item)
                session.flush()
        except IntegrityError:
            skipped += 1
            continue
        created += 1

    return created, skipped


def _ingest_single_source(
    session: Session,
    source: NewsSource,
    fetched_at: datetime,
    timeout_seconds: float,
    source_fetcher: Callable[[str, float], str],
) -> tuple[int, int]:
    last_error: Exception | None = None

    for attempt in range(MAX_FETCH_ATTEMPTS):
        try:
            content = source_fetcher(source.url, timeout_seconds)
            entries = parse_feed_entries(content, fetched_at=fetched_at)
            created, skipped = _persist_entries(session, source, entries, fetched_at)
            _mark_source_success(source, fetched_at)
            session.commit()
            return created, skipped
        except Exception as exc:
            session.rollback()
            last_error = exc
            should_mark_unhealthy = attempt == MAX_FETCH_ATTEMPTS - 1
            _mark_source_failure(source, fetched_at, str(exc), unhealthy=should_mark_unhealthy)
            session.commit()

    raise RuntimeError(f"Failed to ingest source {source.id}: {last_error}") from last_error


def ingest_due_sources(
    session: Session,
    now: datetime | None = None,
    settings: Settings | None = None,
    source_fetcher: Callable[[str, float], str] | None = None,
    *,
    only_unhealthy: bool = False,
) -> IngestionSummary:
    active_settings = settings or get_settings()
    fetched_at = now or datetime.now(UTC)
    _ensure_default_sources(session, active_settings)

    sources = [
        source
        for source in session.execute(_eligible_sources_statement(fetched_at, only_unhealthy)).scalars().all()
        if _source_is_due(source, fetched_at, only_unhealthy)
    ]

    fetcher = source_fetcher or fetch_feed_content
    sources_succeeded = 0
    sources_failed = 0
    items_created = 0
    items_skipped = 0

    for source in sources:
        try:
            created, skipped = _ingest_single_source(
                session,
                source,
                fetched_at,
                active_settings.news_fetch_timeout_seconds,
                fetcher,
            )
        except RuntimeError:
            sources_failed += 1
        else:
            sources_succeeded += 1
            items_created += created
            items_skipped += skipped

    return IngestionSummary(
        sources_seen=len(sources),
        sources_processed=len(sources),
        sources_succeeded=sources_succeeded,
        sources_failed=sources_failed,
        items_created=items_created,
        items_skipped=items_skipped,
    )
