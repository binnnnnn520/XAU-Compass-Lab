from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260402_0004"
down_revision = "20260401_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_runs"),
    )
    op.create_index(
        "ix_strategy_runs_strategy_name_version",
        "strategy_runs",
        ["strategy_name", "version"],
        unique=False,
    )
    op.create_index("ix_strategy_runs_is_active", "strategy_runs", ["is_active"], unique=False)

    op.create_table(
        "signals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False, server_default=sa.text("'XAUUSD'")),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("strength", sa.Numeric(precision=5, scale=4), nullable=False, server_default=sa.text("0")),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False, server_default=sa.text("0")),
        sa.Column("price_at_signal", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column(
            "features_used",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False, server_default=sa.text("'live'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["strategy_run_id"], ["strategy_runs.id"], name="fk_signals_strategy_run_id_strategy_runs"),
        sa.PrimaryKeyConstraint("id", name="pk_signals"),
    )
    op.execute("CREATE INDEX ix_signals_signal_time_desc ON signals (signal_time DESC)")
    op.execute(
        "CREATE INDEX ix_signals_strategy_run_id_signal_time_desc "
        "ON signals (strategy_run_id, signal_time DESC)"
    )
    op.execute(
        "CREATE INDEX ix_signals_direction_signal_time_desc "
        "ON signals (direction, signal_time DESC)"
    )
    op.create_index("ix_signals_source_type", "signals", ["source_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_signals_source_type", table_name="signals")
    op.execute("DROP INDEX IF EXISTS ix_signals_direction_signal_time_desc")
    op.execute("DROP INDEX IF EXISTS ix_signals_strategy_run_id_signal_time_desc")
    op.execute("DROP INDEX IF EXISTS ix_signals_signal_time_desc")
    op.drop_table("signals")

    op.drop_index("ix_strategy_runs_is_active", table_name="strategy_runs")
    op.drop_index("ix_strategy_runs_strategy_name_version", table_name="strategy_runs")
    op.drop_table("strategy_runs")
