from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal, get_engine
from app.services.broker import IBKRPaperSandboxBroker, IBKRPaperSandboxCredentials, IBKRPaperSandboxIBAPIClient
from app.services.live_readiness import collect_parallel_run_observations


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


@celery_app.task(name="app.tasks.live.task_collect_parallel_observations")
def task_collect_parallel_observations(
    *,
    enabled: bool | None = None,
    as_of_iso: str | None = None,
    total_equity: str = "100000.00000000",
) -> dict[str, Any]:
    settings = get_settings()
    collection_enabled = settings.phase5_observation_collection_enabled if enabled is None else enabled
    as_of = _parse_task_datetime(as_of_iso) or datetime.now(UTC)
    if not collection_enabled:
        return {
            "status": "skipped",
            "reason": "phase5_observation_collection_disabled",
            "as_of": as_of.isoformat(),
            "observed_count": 0,
            "skipped_count": 0,
        }

    credentials = IBKRPaperSandboxCredentials.from_env()
    if credentials is None:
        return {
            "status": "skipped",
            "reason": "ibkr_paper_sandbox_credentials_missing",
            "as_of": as_of.isoformat(),
            "observed_count": 0,
            "skipped_count": 0,
        }

    broker = IBKRPaperSandboxBroker(
        client=IBKRPaperSandboxIBAPIClient(expected_account_id=credentials.account_id),
        credentials=credentials,
    )
    engine = get_engine()
    session_factory = SessionLocal
    session_factory.configure(bind=engine)
    session = session_factory()
    try:
        result = collect_parallel_run_observations(
            session,
            broker=broker,
            as_of=as_of,
            total_equity=Decimal(str(total_equity)),
        )
        session.commit()
        return {
            "status": "ok",
            "as_of": result.as_of.isoformat(),
            "observed_count": result.observed_count,
            "skipped_count": result.skipped_count,
        }
    finally:
        session.close()
        engine.dispose()
