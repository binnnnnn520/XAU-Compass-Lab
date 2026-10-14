from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, RiskEvent
from app.services.compliance.retention import build_phase5_retention_policy, evaluate_retention_action


def test_phase5_retention_policy_lists_enforced_five_year_evidence_tables() -> None:
    policy = build_phase5_retention_policy()

    assert policy.retention_years == 5
    rules = {rule.table_name: rule for rule in policy.rules}
    assert rules["audit_logs"].append_only is True
    assert rules["audit_logs"].protected_actions == ("update", "delete")
    assert rules["risk_events"].min_retention_years == 5
    assert rules["paper_orders"].min_retention_years == 5
    assert rules["paper_positions"].min_retention_years == 5
    assert rules["live_parallel_observations"].min_retention_years == 5


def test_phase5_retention_action_rejects_naive_and_under_retention_delete() -> None:
    created_at = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)

    under_retention = evaluate_retention_action(
        table_name="risk_events",
        action="delete",
        record_timestamp=created_at,
        as_of=datetime(2030, 4, 30, 23, 59, tzinfo=UTC),
    )
    after_retention = evaluate_retention_action(
        table_name="risk_events",
        action="delete",
        record_timestamp=created_at,
        as_of=datetime(2031, 5, 1, 0, 0, tzinfo=UTC),
    )
    audit_delete = evaluate_retention_action(
        table_name="audit_logs",
        action="delete",
        record_timestamp=created_at,
        as_of=datetime(2036, 5, 1, 0, 0, tzinfo=UTC),
    )

    assert under_retention.allowed is False
    assert under_retention.reason == "minimum_retention_window_active"
    assert after_retention.allowed is True
    assert audit_delete.allowed is False
    assert audit_delete.reason == "append_only_table"

    with pytest.raises(ValueError, match="UTC-aware"):
        evaluate_retention_action(
            table_name="risk_events",
            action="delete",
            record_timestamp=datetime(2026, 5, 1, 0, 0),
            as_of=datetime(2031, 5, 1, 0, 0, tzinfo=UTC),
        )


def test_phase5_retention_db_triggers_are_installed(schema_engine, db_schema) -> None:
    with schema_engine.connect() as connection:
        trigger_names = set(
            connection.execute(
                text(
                    """
                    SELECT tgname
                    FROM pg_trigger
                    JOIN pg_class ON pg_trigger.tgrelid = pg_class.oid
                    JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
                    WHERE NOT tgisinternal
                    AND pg_namespace.nspname = :schema
                    AND pg_class.relname IN (
                        'audit_logs',
                        'risk_events',
                        'paper_orders',
                        'paper_positions',
                        'live_parallel_observations'
                    )
                    """
                ),
                {"schema": db_schema},
            ).scalars()
        )

    assert {
        "trg_phase5_audit_logs_append_only",
        "trg_phase5_risk_events_min_retention",
        "trg_phase5_paper_orders_min_retention",
        "trg_phase5_paper_positions_min_retention",
        "trg_phase5_live_parallel_observations_min_retention",
    } <= trigger_names


def test_phase5_retention_db_triggers_block_audit_mutation_and_early_risk_delete(
    db_session,
    schema_engine,
    db_schema,
) -> None:
    db_session.execute(text(f'SET search_path TO "{db_schema}"'))
    audit_log = AuditLog(
        action="phase5_retention_test",
        entity_type="live_readiness",
        entity_id=None,
        actor="phase5_admin",
        old_value=None,
        new_value={"retention": "test"},
        ip_address=None,
    )
    risk_event = RiskEvent(
        event_type="phase5_retention_test",
        severity="warning",
        trigger_value=None,
        threshold_value=None,
        action_taken="record_retention_test",
        related_order_id=None,
        description="Phase 5 retention trigger test",
        metadata_json={},
    )
    db_session.add_all([audit_log, risk_event])
    db_session.commit()

    with schema_engine.connect() as connection:
        transaction = connection.begin()
        assert (
            connection.execute(
                text(f'SELECT count(*) FROM "{db_schema}".audit_logs WHERE id = CAST(:id AS uuid)'),
                {"id": str(audit_log.id)},
            ).scalar_one()
            == 1
        )
        with pytest.raises(DBAPIError):
            connection.execute(
                text(f'UPDATE "{db_schema}".audit_logs SET actor = \'mutated\' WHERE id = CAST(:id AS uuid)'),
                {"id": str(audit_log.id)},
            )
        transaction.rollback()

    with schema_engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError):
            connection.execute(
                text(f'DELETE FROM "{db_schema}".risk_events WHERE id = CAST(:id AS uuid)'),
                {"id": str(risk_event.id)},
            )
        transaction.rollback()
