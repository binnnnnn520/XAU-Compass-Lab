from __future__ import annotations

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal, get_engine
from app.services.llm_analysis import analyze_news_items, build_default_analyzer


@celery_app.task(name="app.tasks.analysis.task_analyze_news")
def task_analyze_news(*, limit: int = 100) -> dict[str, int]:
    engine = get_engine()
    session_factory = SessionLocal
    session_factory.configure(bind=engine)
    session = session_factory()
    try:
        settings = get_settings()
        analyzer = build_default_analyzer(settings)
        summary = analyze_news_items(session, analyzer=analyzer, limit=limit)
        return {
            "items_seen": summary.items_seen,
            "items_analyzed": summary.items_analyzed,
            "items_failed": summary.items_failed,
            "sentiments_created": summary.sentiments_created,
            "event_tags_created": summary.event_tags_created,
        }
    finally:
        session.close()
        engine.dispose()
