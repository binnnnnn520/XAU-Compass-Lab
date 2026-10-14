from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260408_0006"
down_revision = "20260408_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False, server_default=sa.text("'XAUUSD'")),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("order_type", sa.String(length=20), nullable=False, server_default=sa.text("'MARKET'")),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("limit_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("slippage", sa.Numeric(precision=20, scale=8), nullable=False, server_default=sa.text("0")),
        sa.Column("commission", sa.Numeric(precision=20, scale=8), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], name="fk_paper_orders_signal_id_signals"),
        sa.PrimaryKeyConstraint("id", name="pk_paper_orders"),
    )
    op.create_index("ix_paper_orders_signal_id", "paper_orders", ["signal_id"], unique=False)
    op.create_index("ix_paper_orders_status", "paper_orders", ["status"], unique=False)
    op.execute("CREATE INDEX ix_paper_orders_created_at_desc ON paper_orders (created_at DESC)")
    op.execute("CREATE INDEX ix_paper_orders_symbol_created_at_desc ON paper_orders (symbol, created_at DESC)")

    op.create_table(
        "paper_positions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("symbol", sa.String(length=20), nullable=False, server_default=sa.text("'XAUUSD'")),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(precision=20, scale=8), nullable=False, server_default=sa.text("0")),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=8), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=10), nullable=False, server_default=sa.text("'open'")),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exit_order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(
            ["entry_order_id"],
            ["paper_orders.id"],
            name="fk_paper_positions_entry_order_id_paper_orders",
        ),
        sa.ForeignKeyConstraint(
            ["exit_order_id"],
            ["paper_orders.id"],
            name="fk_paper_positions_exit_order_id_paper_orders",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_paper_positions"),
    )
    op.create_index("ix_paper_positions_status_symbol", "paper_positions", ["status", "symbol"], unique=False)
    op.execute("CREATE INDEX ix_paper_positions_opened_at_desc ON paper_positions (opened_at DESC)")

    op.create_table(
        "risk_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("trigger_value", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("threshold_value", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("action_taken", sa.String(length=50), nullable=False),
        sa.Column("related_order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(
            ["related_order_id"],
            ["paper_orders.id"],
            name="fk_risk_events_related_order_id_paper_orders",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_risk_events"),
    )
    op.execute("CREATE INDEX ix_risk_events_event_type_created_at_desc ON risk_events (event_type, created_at DESC)")
    op.execute("CREATE INDEX ix_risk_events_severity_created_at_desc ON risk_events (severity, created_at DESC)")

    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.String(length=50), nullable=False, server_default=sa.text("'system'")),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.execute("CREATE INDEX ix_audit_logs_action_created_at_desc ON audit_logs (action, created_at DESC)")
    op.create_index("ix_audit_logs_entity_type_entity_id", "audit_logs", ["entity_type", "entity_id"], unique=False)
    op.execute("CREATE INDEX ix_audit_logs_created_at_desc ON audit_logs (created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_created_at_desc")
    op.drop_index("ix_audit_logs_entity_type_entity_id", table_name="audit_logs")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_action_created_at_desc")
    op.drop_table("audit_logs")

    op.execute("DROP INDEX IF EXISTS ix_risk_events_severity_created_at_desc")
    op.execute("DROP INDEX IF EXISTS ix_risk_events_event_type_created_at_desc")
    op.drop_table("risk_events")

    op.execute("DROP INDEX IF EXISTS ix_paper_positions_opened_at_desc")
    op.drop_index("ix_paper_positions_status_symbol", table_name="paper_positions")
    op.drop_table("paper_positions")

    op.execute("DROP INDEX IF EXISTS ix_paper_orders_symbol_created_at_desc")
    op.execute("DROP INDEX IF EXISTS ix_paper_orders_created_at_desc")
    op.drop_index("ix_paper_orders_status", table_name="paper_orders")
    op.drop_index("ix_paper_orders_signal_id", table_name="paper_orders")
    op.drop_table("paper_orders")
