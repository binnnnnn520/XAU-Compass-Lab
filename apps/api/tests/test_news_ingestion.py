from __future__ import annotations

from datetime import UTC, datetime
import json

from app.celery_app import celery_app
from app.config import Settings
from app.models import NewsItem, NewsSource
from app.services.news_ingestion import ingest_due_sources, parse_feed_entries


RSS_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Gold News</title>
    <language>en</language>
    <item>
      <title>Gold rises as Fed cut bets grow</title>
      <link>https://example.com/news-1</link>
      <description>Risk sentiment supports bullion.</description>
      <author>Desk</author>
      <pubDate>Tue, 01 Apr 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Dollar slips, gold holds gains</title>
      <link>https://example.com/news-2</link>
      <description>Second item body.</description>
      <pubDate>Tue, 01 Apr 2026 11:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_fetch_feed_content_sends_user_agent_header(monkeypatch) -> None:
    from app.services.news_ingestion import service as news_service

    captured: dict[str, object] = {}

    class _FakeResponse:
        text = "<rss></rss>"

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured["headers"] = kwargs.get("headers")

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

        def get(self, url: str) -> _FakeResponse:
            captured["url"] = url
            return _FakeResponse()

    monkeypatch.setattr(news_service.httpx, "Client", _FakeClient)

    content = news_service.fetch_feed_content("https://example.com/feed", 10.0)

    assert content == "<rss></rss>"
    headers = captured["headers"]
    assert headers is not None and headers.get("User-Agent") == news_service.NEWS_FEED_USER_AGENT


def _settings_with_default_sources() -> Settings:
    return Settings(
        default_news_sources_json=json.dumps(
            [
                {
                    "name": "Reuters RSS",
                    "url": "https://example.com/reuters.xml",
                    "source_type": "rss",
                    "fetch_interval": 300,
                },
                {
                    "name": "Kitco RSS",
                    "url": "https://example.com/kitco.xml",
                    "source_type": "rss",
                    "fetch_interval": 300,
                },
            ]
        )
    )


def test_settings_default_news_sources_configures_four_phase1_sources() -> None:
    sources = Settings().default_news_sources

    assert len(sources) >= 4
    assert len({source["name"] for source in sources}) >= 4


def test_parse_feed_entries_normalizes_published_at_to_utc() -> None:
    entries = parse_feed_entries(RSS_FEED, fetched_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC))

    assert len(entries) == 2
    assert entries[0].published_at == datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    assert entries[0].language == "en"
    assert entries[0].raw_data["title"] == "Gold rises as Fed cut bets grow"


def test_ingest_due_sources_handles_two_sources_and_deduplicates(db_session) -> None:
    settings = _settings_with_default_sources()

    def fetcher(url: str, timeout_seconds: float) -> str:
        assert timeout_seconds == settings.news_fetch_timeout_seconds
        return RSS_FEED

    summary = ingest_due_sources(
        db_session,
        now=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        settings=settings,
        source_fetcher=fetcher,
    )

    assert summary.sources_processed == 2
    assert summary.sources_succeeded == 2
    assert summary.items_created == 4
    assert summary.items_skipped == 0

    second_summary = ingest_due_sources(
        db_session,
        now=datetime(2026, 4, 1, 12, 6, tzinfo=UTC),
        settings=settings,
        source_fetcher=fetcher,
    )

    assert second_summary.sources_processed == 2
    assert second_summary.items_created == 0
    assert second_summary.items_skipped == 4
    assert db_session.query(NewsSource).count() == 2
    assert db_session.query(NewsItem).count() == 4


def test_ingest_due_sources_marks_failing_source_unhealthy_after_retries(db_session) -> None:
    source = NewsSource(
        name="Broken RSS",
        source_type="rss",
        url="https://example.com/broken.xml",
        fetch_interval=300,
    )
    db_session.add(source)
    db_session.commit()

    attempts = {"count": 0}

    def failing_fetcher(url: str, timeout_seconds: float) -> str:
        attempts["count"] += 1
        raise RuntimeError("upstream timeout")

    summary = ingest_due_sources(
        db_session,
        now=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        settings=Settings(),
        source_fetcher=failing_fetcher,
    )

    db_session.refresh(source)

    assert attempts["count"] == 3
    assert summary.sources_failed == 1
    assert source.health_status == "unhealthy"
    assert source.config["consecutive_failures"] == 3
    assert source.config["last_error"] == "upstream timeout"


def test_unhealthy_source_probe_can_recover_source_health(db_session) -> None:
    source = NewsSource(
        name="Recovered RSS",
        source_type="rss",
        url="https://example.com/recovered.xml",
        fetch_interval=300,
        health_status="unhealthy",
        config={"consecutive_failures": 3, "last_error": "timeout"},
    )
    db_session.add(source)
    db_session.commit()

    summary = ingest_due_sources(
        db_session,
        now=datetime(2026, 4, 1, 13, 0, tzinfo=UTC),
        settings=Settings(),
        source_fetcher=lambda url, timeout_seconds: RSS_FEED,
        only_unhealthy=True,
    )

    db_session.refresh(source)

    assert summary.sources_processed == 1
    assert summary.sources_succeeded == 1
    assert source.health_status == "healthy"
    assert source.config["consecutive_failures"] == 0
    assert source.last_fetched_at == datetime(2026, 4, 1, 13, 0, tzinfo=UTC)


def test_celery_beat_schedule_wires_news_tasks() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["fetch-news-every-5min"]["task"] == "app.tasks.news.task_fetch_news"
    assert schedule["probe-unhealthy-news-sources-hourly"]["task"] == "app.tasks.news.task_fetch_news"
    assert schedule["probe-unhealthy-news-sources-hourly"]["kwargs"] == {"only_unhealthy": True}
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"
