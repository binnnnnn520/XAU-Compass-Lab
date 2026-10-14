from __future__ import annotations

import uuid

from sqlalchemy import inspect, text


def test_alembic_migration_creates_task10_tables_and_indexes(admin_engine, db_schema: str) -> None:
    inspector = inspect(admin_engine)
    tables = set(inspector.get_table_names(schema=db_schema))

    assert {"paper_orders", "paper_positions", "risk_events", "audit_logs"} <= tables

    order_columns = {column["name"]: column for column in inspector.get_columns("paper_orders", schema=db_schema)}
    assert order_columns["signal_id"]["type"].python_type is uuid.UUID
    assert order_columns["quantity"]["type"].precision == 20
    assert order_columns["quantity"]["type"].scale == 8
    assert order_columns["price"]["type"].precision == 20
    assert order_columns["price"]["type"].scale == 8
    assert order_columns["stop_loss"]["type"].precision == 20
    assert order_columns["stop_loss"]["type"].scale == 8
    assert order_columns["take_profit"]["type"].precision == 20
    assert order_columns["take_profit"]["type"].scale == 8
    assert order_columns["filled_at"]["type"].timezone is True

    position_columns = {column["name"]: column for column in inspector.get_columns("paper_positions", schema=db_schema)}
    assert position_columns["entry_price"]["type"].precision == 20
    assert position_columns["entry_price"]["type"].scale == 8
    assert position_columns["current_price"]["type"].precision == 20
    assert position_columns["current_price"]["type"].scale == 8
    assert position_columns["stop_loss"]["type"].precision == 20
    assert position_columns["stop_loss"]["type"].scale == 8
    assert position_columns["take_profit"]["type"].precision == 20
    assert position_columns["take_profit"]["type"].scale == 8
    assert position_columns["trailing_stop_distance"]["type"].precision == 20
    assert position_columns["trailing_stop_distance"]["type"].scale == 8
    assert position_columns["trailing_stop_price"]["type"].precision == 20
    assert position_columns["trailing_stop_price"]["type"].scale == 8
    assert position_columns["opened_at"]["type"].timezone is True
    assert position_columns["updated_at"]["type"].timezone is True

    event_columns = {column["name"]: column for column in inspector.get_columns("risk_events", schema=db_schema)}
    assert event_columns["trigger_value"]["type"].precision == 20
    assert event_columns["trigger_value"]["type"].scale == 8
    assert event_columns["threshold_value"]["type"].precision == 20
    assert event_columns["threshold_value"]["type"].scale == 8
    assert event_columns["created_at"]["type"].timezone is True

    audit_columns = {column["name"]: column for column in inspector.get_columns("audit_logs", schema=db_schema)}
    assert audit_columns["entity_id"]["type"].python_type is uuid.UUID
    assert audit_columns["created_at"]["type"].timezone is True

    order_indexes = {index["name"] for index in inspector.get_indexes("paper_orders", schema=db_schema)}
    assert "ix_paper_orders_signal_id" in order_indexes
    assert "ix_paper_orders_status" in order_indexes

    position_indexes = {index["name"] for index in inspector.get_indexes("paper_positions", schema=db_schema)}
    assert "ix_paper_positions_status_symbol" in position_indexes

    audit_indexes = {index["name"] for index in inspector.get_indexes("audit_logs", schema=db_schema)}
    assert "ix_audit_logs_entity_type_entity_id" in audit_indexes

    with admin_engine.connect() as connection:
        index_defs = dict(
            connection.execute(
                text(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = :schema
                      AND tablename IN ('paper_orders', 'paper_positions', 'risk_events', 'audit_logs')
                    """
                ),
                {"schema": db_schema},
            ).all()
        )

    assert "created_at DESC" in index_defs["ix_paper_orders_created_at_desc"]
    assert "symbol, created_at DESC" in index_defs["ix_paper_orders_symbol_created_at_desc"]
    assert "opened_at DESC" in index_defs["ix_paper_positions_opened_at_desc"]
    assert "event_type, created_at DESC" in index_defs["ix_risk_events_event_type_created_at_desc"]
    assert "severity, created_at DESC" in index_defs["ix_risk_events_severity_created_at_desc"]
    assert "action, created_at DESC" in index_defs["ix_audit_logs_action_created_at_desc"]
    assert "created_at DESC" in index_defs["ix_audit_logs_created_at_desc"]
