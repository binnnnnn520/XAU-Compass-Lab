from __future__ import annotations

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal, get_engine
from app.services.news_ingestion import ingest_due_sources


@celery_app.task(name="app.tasks.news.task_fetch_news")
def task_fetch_news(*, only_unhealthy: bool = False) -> dict[str, int]:
    engine = get_engine()
    session_factory = SessionLocal
    session_factory.configure(bind=engine)
    session = session_factory()
    try:
        summary = ingest_due_sources(session, settings=get_settings(), only_unhealthy=only_unhealthy)
        return {
            "sources_seen": summary.sources_seen,
            "sources_processed": summary.sources_processed,
            "sources_succeeded": summary.sources_succeeded,
            "sources_failed": summary.sources_failed,
            "items_created": summary.items_created,
            "items_skipped": summary.items_skipped,
        }
    finally:
        session.close()
        engine.dispose()
