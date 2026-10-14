from __future__ import annotations

from alembic import op


revision = "20260501_0012"
down_revision = "20260501_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION phase5_block_audit_log_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs are append-only for Phase 5 compliance';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION phase5_enforce_min_retention()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.created_at IS NULL THEN
                RAISE EXCEPTION 'Phase 5 retention requires created_at on %', TG_TABLE_NAME;
            END IF;
            IF OLD.created_at > NOW() - INTERVAL '5 years' THEN
                RAISE EXCEPTION 'Phase 5 retention prevents deleting % rows before 5 years', TG_TABLE_NAME;
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_phase5_audit_logs_append_only ON audit_logs")
    op.execute(
        """
        CREATE TRIGGER trg_phase5_audit_logs_append_only
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION phase5_block_audit_log_mutation()
        """
    )

    for table_name in (
        "risk_events",
        "paper_orders",
        "paper_positions",
        "live_parallel_observations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_phase5_{table_name}_min_retention ON {table_name}")
        op.execute(
            f"""
            CREATE TRIGGER trg_phase5_{table_name}_min_retention
            BEFORE DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION phase5_enforce_min_retention()
            """
        )


def downgrade() -> None:
    for table_name in (
        "live_parallel_observations",
        "paper_positions",
        "paper_orders",
        "risk_events",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_phase5_{table_name}_min_retention ON {table_name}")
    op.execute("DROP TRIGGER IF EXISTS trg_phase5_audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS phase5_enforce_min_retention()")
    op.execute("DROP FUNCTION IF EXISTS phase5_block_audit_log_mutation()")
