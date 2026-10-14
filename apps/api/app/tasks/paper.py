from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.celery_app import celery_app
from app.database import SessionLocal, get_engine
from app.services.paper_execution import check_open_position_stops, execute_pending_signals


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


@celery_app.task(name="app.tasks.paper.task_check_stops")
def task_check_stops(*, as_of_iso: str | None = None) -> dict[str, Any]:
    as_of = _parse_task_datetime(as_of_iso) or datetime.now(UTC)
    engine = get_engine()
    session_factory = SessionLocal
    session_factory.configure(bind=engine)
    session = session_factory()
    try:
        positions_closed = check_open_position_stops(session, as_of=as_of)
        session.commit()
        return {
            "checked_at": as_of.isoformat(),
            "positions_closed": positions_closed,
        }
    finally:
        session.close()
        engine.dispose()


@celery_app.task(name="app.tasks.paper.task_execute_pending_signals")
def task_execute_pending_signals(*, limit: int = 200) -> dict[str, Any]:
    engine = get_engine()
    session_factory = SessionLocal
    session_factory.configure(bind=engine)
    session = session_factory()
    try:
        result = execute_pending_signals(session, limit=limit)
        session.commit()
        return result
    finally:
        session.close()
        engine.dispose()
