from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.database import get_database_url


@pytest.fixture(scope="session")
def database_url() -> str:
    return get_database_url()


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    return Config(str(API_ROOT / "alembic.ini"))


@pytest.fixture(scope="session")
def admin_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def db_schema(alembic_config: Config, admin_engine: Engine) -> str:
    schema = f"task2_{uuid.uuid4().hex[:12]}"
    alembic_config.attributes["schema"] = schema
    command.upgrade(alembic_config, "head")
    yield schema
    with admin_engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


@pytest.fixture(scope="session")
def schema_engine(database_url: str, db_schema: str) -> Engine:
    engine = create_engine(database_url, future=True, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def set_search_path(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f'SET search_path TO "{db_schema}"')
        cursor.close()

    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(schema_engine: Engine):
    from sqlalchemy.orm import Session

    session = Session(bind=schema_engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        with schema_engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE live_parallel_observations, economic_events, model_versions, audit_logs, risk_events, paper_positions, paper_orders, backtest_runs, signals, "
                    "strategy_runs, sentiment_scores, event_tags, market_bars, news_items, news_sources "
                    "RESTART IDENTITY CASCADE"
                )
            )
