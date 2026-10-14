from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models import EventTag, MarketBar, ModelVersion, NewsItem, NewsSource, SentimentScore, Signal, StrategyRun

STATUS_CHECK_CONSTRAINT = "ck_news_items_news_item_status"


def test_alembic_migration_creates_phase2_tables_and_indexes(admin_engine, db_schema: str) -> None:
    inspector = inspect(admin_engine)
    tables = set(inspector.get_table_names(schema=db_schema))

    assert {
        "alembic_version",
        "event_tags",
        "market_bars",
        "model_versions",
        "news_items",
        "news_sources",
        "sentiment_scores",
        "signals",
        "strategy_runs",
    } <= tables

    news_source_columns = {
        column["name"]: column for column in inspector.get_columns("news_sources", schema=db_schema)
    }
    assert news_source_columns["id"]["type"].python_type is uuid.UUID
    assert news_source_columns["last_fetched_at"]["type"].timezone is True
    assert news_source_columns["updated_at"]["type"].timezone is True

    news_item_columns = {
        column["name"]: column for column in inspector.get_columns("news_items", schema=db_schema)
    }
    assert news_item_columns["id"]["type"].python_type is uuid.UUID
    assert news_item_columns["published_at"]["type"].timezone is True
    assert news_item_columns["status"]["default"] == "'pending'::character varying"
    news_item_checks = inspector.get_check_constraints("news_items", schema=db_schema)
    assert any(
        constraint["name"] == STATUS_CHECK_CONSTRAINT
        and "pending" in constraint["sqltext"]
        and "analyzed" in constraint["sqltext"]
        and "failed" in constraint["sqltext"]
        for constraint in news_item_checks
    )
    assert any(
        "pending" in constraint["sqltext"]
        and "analyzed" in constraint["sqltext"]
        and "failed" in constraint["sqltext"]
        for constraint in news_item_checks
    )

    market_bar_columns = {
        column["name"]: column for column in inspector.get_columns("market_bars", schema=db_schema)
    }
    assert market_bar_columns["id"]["type"].python_type is uuid.UUID
    assert market_bar_columns["bar_time"]["type"].timezone is True
    assert market_bar_columns["symbol"]["default"] == "'XAUUSD'::character varying"
    for column_name in ("open", "high", "low", "close", "volume"):
        assert market_bar_columns[column_name]["type"].precision == 20
        assert market_bar_columns[column_name]["type"].scale == 8

    sentiment_columns = {
        column["name"]: column for column in inspector.get_columns("sentiment_scores", schema=db_schema)
    }
    assert sentiment_columns["news_id"]["type"].python_type is uuid.UUID
    assert sentiment_columns["score"]["type"].precision == 5
    assert sentiment_columns["score"]["type"].scale == 4
    assert sentiment_columns["created_at"]["type"].timezone is True

    event_tag_columns = {
        column["name"]: column for column in inspector.get_columns("event_tags", schema=db_schema)
    }
    assert event_tag_columns["news_id"]["type"].python_type is uuid.UUID
    assert event_tag_columns["relevance_score"]["type"].precision == 5
    assert event_tag_columns["relevance_score"]["type"].scale == 4
    assert event_tag_columns["created_at"]["type"].timezone is True

    strategy_run_columns = {
        column["name"]: column for column in inspector.get_columns("strategy_runs", schema=db_schema)
    }
    assert strategy_run_columns["id"]["type"].python_type is uuid.UUID
    assert strategy_run_columns["is_active"]["default"] == "false"
    assert strategy_run_columns["created_at"]["type"].timezone is True
    assert strategy_run_columns["updated_at"]["type"].timezone is True

    signal_columns = {
        column["name"]: column for column in inspector.get_columns("signals", schema=db_schema)
    }
    assert signal_columns["strategy_run_id"]["type"].python_type is uuid.UUID
    assert signal_columns["signal_time"]["type"].timezone is True
    assert signal_columns["strength"]["type"].precision == 5
    assert signal_columns["strength"]["type"].scale == 4
    assert signal_columns["confidence"]["type"].precision == 5
    assert signal_columns["confidence"]["type"].scale == 4
    assert signal_columns["price_at_signal"]["type"].precision == 20
    assert signal_columns["price_at_signal"]["type"].scale == 8
    assert signal_columns["created_at"]["type"].timezone is True

    model_version_columns = {
        column["name"]: column for column in inspector.get_columns("model_versions", schema=db_schema)
    }
    assert model_version_columns["id"]["type"].python_type is uuid.UUID
    assert model_version_columns["feature_schema"]["default"] == "'{}'::jsonb"
    assert model_version_columns["metrics"]["default"] == "'{}'::jsonb"
    assert model_version_columns["is_active"]["default"] == "false"
    assert model_version_columns["trained_at"]["type"].timezone is True
    assert model_version_columns["created_at"]["type"].timezone is True
    assert model_version_columns["updated_at"]["type"].timezone is True

    news_source_indexes = {index["name"] for index in inspector.get_indexes("news_sources", schema=db_schema)}
    assert "ix_news_sources_is_active_health_status" in news_source_indexes
    assert "ix_news_sources_source_type" in news_source_indexes

    strategy_run_indexes = {index["name"] for index in inspector.get_indexes("strategy_runs", schema=db_schema)}
    assert "ix_strategy_runs_strategy_name_version" in strategy_run_indexes
    assert "ix_strategy_runs_is_active" in strategy_run_indexes

    signal_indexes = {index["name"] for index in inspector.get_indexes("signals", schema=db_schema)}
    assert "ix_signals_source_type" in signal_indexes

    model_version_indexes = {index["name"] for index in inspector.get_indexes("model_versions", schema=db_schema)}
    assert "ix_model_versions_model_name_version" in model_version_indexes
    assert "ix_model_versions_model_type_status" in model_version_indexes
    assert "ix_model_versions_is_active" in model_version_indexes

    news_item_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("news_items", schema=db_schema)
    }
    assert ("title_hash", "source_id") in news_item_uniques

    market_bar_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("market_bars", schema=db_schema)
    }
    assert ("symbol", "timeframe", "bar_time") in market_bar_uniques

    sentiment_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("sentiment_scores", schema=db_schema)
    }
    assert ("news_id", "analyzer_type") in sentiment_uniques

    event_tag_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("event_tags", schema=db_schema)
    }
    assert ("news_id", "tag_type", "tag_value") in event_tag_uniques

    model_version_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("model_versions", schema=db_schema)
    }
    assert ("model_name", "version") in model_version_uniques

    with admin_engine.connect() as connection:
        index_defs = dict(
            connection.execute(
                text(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = :schema
                      AND tablename IN ('news_items', 'market_bars', 'sentiment_scores', 'event_tags', 'signals')
                    """
                ),
                {"schema": db_schema},
            ).all()
        )

    assert "published_at DESC" in index_defs["ix_news_items_published_at_desc"]
    assert "source_id, published_at DESC" in index_defs["ix_news_items_source_id_published_at_desc"]
    assert "symbol, timeframe, bar_time DESC" in index_defs["ix_market_bars_symbol_timeframe_bar_time_desc"]
    assert "created_at DESC" in index_defs["ix_sentiment_scores_created_at_desc"]
    assert "sentiment, created_at DESC" in index_defs["ix_sentiment_scores_sentiment_created_at_desc"]
    assert "tag_type, created_at DESC" in index_defs["ix_event_tags_tag_type_created_at_desc"]
    assert "signal_time DESC" in index_defs["ix_signals_signal_time_desc"]
    assert "strategy_run_id, signal_time DESC" in index_defs["ix_signals_strategy_run_id_signal_time_desc"]
    assert "direction, signal_time DESC" in index_defs["ix_signals_direction_signal_time_desc"]


def test_model_metadata_matches_required_unique_constraints() -> None:
    news_item_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in NewsItem.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("title_hash", "source_id") in news_item_uniques

    market_bar_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in MarketBar.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("symbol", "timeframe", "bar_time") in market_bar_uniques

    sentiment_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in SentimentScore.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("news_id", "analyzer_type") in sentiment_uniques

    event_tag_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in EventTag.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("news_id", "tag_type", "tag_value") in event_tag_uniques

    strategy_run_indexes = {index.name for index in StrategyRun.__table__.indexes}
    assert "ix_strategy_runs_strategy_name_version" in strategy_run_indexes
    assert "ix_strategy_runs_is_active" in strategy_run_indexes

    signal_indexes = {index.name for index in Signal.__table__.indexes}
    assert "ix_signals_signal_time_desc" in signal_indexes
    assert "ix_signals_strategy_run_id_signal_time_desc" in signal_indexes
    assert "ix_signals_direction_signal_time_desc" in signal_indexes
    assert "ix_signals_source_type" in signal_indexes

    model_version_indexes = {index.name for index in ModelVersion.__table__.indexes}
    assert "ix_model_versions_model_name_version" in model_version_indexes
    assert "ix_model_versions_model_type_status" in model_version_indexes
    assert "ix_model_versions_is_active" in model_version_indexes

    news_item_checks = {
        (constraint.name, str(constraint.sqltext))
        for constraint in NewsItem.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert any(
        constraint_name == STATUS_CHECK_CONSTRAINT
        and "pending" in constraint_sql
        and "analyzed" in constraint_sql
        and "failed" in constraint_sql
        for constraint_name, constraint_sql in news_item_checks
    )


def test_phase2_table_crud_smoke(db_session) -> None:
    source = NewsSource(
        name="Reuters RSS",
        source_type="rss",
        url="https://example.com/reuters.xml",
        last_fetched_at=datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    assert isinstance(source.id, uuid.UUID)
    assert source.created_at.tzinfo == UTC
    assert source.health_status == "healthy"

    item = NewsItem(
        source_id=source.id,
        title="Gold rebounds on policy uncertainty",
        content="Sample body",
        published_at=datetime(2026, 4, 1, 1, 0, tzinfo=UTC),
        title_hash="abc123" * 10 + "ab12",
        raw_data={"source": "rss"},
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    assert isinstance(item.id, uuid.UUID)
    assert item.status == "pending"
    assert item.published_at.tzinfo == UTC

    item.status = "analyzed"
    db_session.commit()
    db_session.refresh(item)
    assert item.status == "analyzed"

    sentiment = SentimentScore(
        news_id=item.id,
        analyzer_type="rule_based",
        sentiment="positive",
        score=Decimal("0.6500"),
        confidence=Decimal("0.8000"),
        reasoning="Matched dovish rate-cut language.",
        metadata_json={"matched_positive_keywords": ["rate cut"]},
    )
    event_tag = EventTag(
        news_id=item.id,
        tag_type="monetary_policy",
        tag_value="fed_rate_cut",
        relevance_score=Decimal("0.9500"),
        metadata_json={"matched_keyword": "rate cut"},
    )
    db_session.add(sentiment)
    db_session.add(event_tag)
    db_session.commit()
    db_session.refresh(sentiment)
    db_session.refresh(event_tag)

    assert isinstance(sentiment.id, uuid.UUID)
    assert isinstance(sentiment.score, Decimal)
    assert sentiment.created_at.tzinfo == UTC
    assert isinstance(event_tag.id, uuid.UUID)
    assert isinstance(event_tag.relevance_score, Decimal)
    assert event_tag.created_at.tzinfo == UTC

    bar = MarketBar(
        timeframe="1h",
        bar_time=datetime(2026, 4, 1, 1, 0, tzinfo=UTC),
        open=Decimal("2289.12000000"),
        high=Decimal("2294.56000000"),
        low=Decimal("2287.78000000"),
        close=Decimal("2292.34000000"),
    )
    db_session.add(bar)
    db_session.commit()
    db_session.refresh(bar)

    assert isinstance(bar.id, uuid.UUID)
    assert bar.symbol == "XAUUSD"
    assert isinstance(bar.close, Decimal)
    assert bar.volume == Decimal("0")
    assert bar.bar_time.tzinfo == UTC

    fetched_item = db_session.get(NewsItem, item.id)
    fetched_bar = db_session.get(MarketBar, bar.id)
    strategy_run = StrategyRun(
        strategy_name="sentiment_momentum_v1",
        version="1.0.0",
        parameters={"lookback_hours": 24},
        is_active=True,
    )
    db_session.add(strategy_run)
    db_session.commit()
    db_session.refresh(strategy_run)

    signal = Signal(
        strategy_run_id=strategy_run.id,
        signal_time=datetime(2026, 4, 1, 2, 0, tzinfo=UTC),
        direction="BUY",
        strength=Decimal("0.7200"),
        confidence=Decimal("0.8100"),
        price_at_signal=Decimal("2292.34000000"),
        features_used={"sentiment_mean": "0.6500", "price_momentum_4h": "0.0021"},
        reasoning="Rule-based buy signal.",
    )
    db_session.add(signal)
    db_session.commit()
    db_session.refresh(signal)

    assert fetched_item is not None
    assert fetched_bar is not None
    assert isinstance(strategy_run.id, uuid.UUID)
    assert strategy_run.updated_at.tzinfo == UTC
    assert isinstance(signal.id, uuid.UUID)
    assert signal.created_at.tzinfo == UTC
    assert signal.features_used["sentiment_mean"] == "0.6500"

    db_session.delete(signal)
    db_session.delete(strategy_run)
    db_session.delete(event_tag)
    db_session.delete(sentiment)
    db_session.delete(fetched_item)
    db_session.delete(fetched_bar)
    db_session.delete(source)
    db_session.commit()

    assert db_session.get(NewsItem, item.id) is None
    assert db_session.get(MarketBar, bar.id) is None
    assert db_session.get(NewsSource, source.id) is None


def test_sentiment_score_duplicate_news_id_and_analyzer_type_fails(db_session) -> None:
    item = NewsItem(
        title="Fed signals a rate cut",
        published_at=datetime(2026, 4, 1, 4, 0, tzinfo=UTC),
        title_hash="s" * 64,
    )
    db_session.add(item)
    db_session.commit()

    first = SentimentScore(
        news_id=item.id,
        analyzer_type="rule_based",
        sentiment="positive",
        score=Decimal("0.6500"),
        confidence=Decimal("0.8000"),
    )
    duplicate = SentimentScore(
        news_id=item.id,
        analyzer_type="rule_based",
        sentiment="neutral",
        score=Decimal("0.0000"),
        confidence=Decimal("0.5000"),
    )

    db_session.add(first)
    db_session.commit()

    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_event_tag_duplicate_news_type_value_fails(db_session) -> None:
    item = NewsItem(
        title="War risk lifts gold",
        published_at=datetime(2026, 4, 1, 5, 0, tzinfo=UTC),
        title_hash="e" * 64,
    )
    db_session.add(item)
    db_session.commit()

    first = EventTag(
        news_id=item.id,
        tag_type="geopolitical",
        tag_value="war_escalation",
        relevance_score=Decimal("0.9500"),
    )
    duplicate = EventTag(
        news_id=item.id,
        tag_type="geopolitical",
        tag_value="war_escalation",
        relevance_score=Decimal("0.8500"),
    )

    db_session.add(first)
    db_session.commit()

    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_news_item_duplicate_title_hash_per_source_fails(db_session) -> None:
    source = NewsSource(name="Bloomberg RSS", source_type="rss", url="https://example.com/bloomberg.xml")
    db_session.add(source)
    db_session.commit()

    published_at = datetime(2026, 4, 1, 2, 0, tzinfo=UTC)
    first = NewsItem(
        source_id=source.id,
        title="Fed remarks support gold",
        published_at=published_at,
        title_hash="f" * 64,
    )
    duplicate = NewsItem(
        source_id=source.id,
        title="Fed remarks support gold updated",
        published_at=published_at,
        title_hash="f" * 64,
    )

    db_session.add(first)
    db_session.commit()

    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_market_bar_duplicate_symbol_timeframe_bar_time_fails(db_session) -> None:
    bar_time = datetime(2026, 4, 1, 3, 0, tzinfo=UTC)
    first = MarketBar(
        timeframe="1h",
        bar_time=bar_time,
        open=Decimal("2290.00000000"),
        high=Decimal("2295.00000000"),
        low=Decimal("2288.00000000"),
        close=Decimal("2291.00000000"),
        volume=Decimal("10.50000000"),
    )
    duplicate = MarketBar(
        timeframe="1h",
        bar_time=bar_time,
        open=Decimal("2291.00000000"),
        high=Decimal("2296.00000000"),
        low=Decimal("2289.00000000"),
        close=Decimal("2292.00000000"),
        volume=Decimal("11.50000000"),
    )

    db_session.add(first)
    db_session.commit()

    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_news_item_invalid_status_is_rejected(db_session) -> None:
    with pytest.raises(ValueError, match="status must be one of: pending, analyzed, failed"):
        db_session.add(
            NewsItem(
                title="Invalid status row",
                published_at=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
                title_hash="z" * 64,
                status="queued",
            )
        )
