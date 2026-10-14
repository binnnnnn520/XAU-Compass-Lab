from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260501_0011"
down_revision = "20260430_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_parallel_observations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("signal_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False, server_default=sa.text("'XAUUSD'")),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paper_direction", sa.String(length=10), nullable=False),
        sa.Column("live_direction", sa.String(length=10), nullable=False),
        sa.Column("paper_order_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("live_order_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paper_fill_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("live_fill_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("order_notional", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("dry_run_status", sa.String(length=20), nullable=False),
        sa.Column("guard_passed", sa.Boolean(), nullable=False),
        sa.Column("risk_event_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id", name="pk_live_parallel_observations"),
    )
    op.create_index(
        "ix_live_parallel_observations_signal_time_desc",
        "live_parallel_observations",
        [sa.text("signal_time DESC")],
        unique=False,
    )
    op.create_index(
        "ix_live_parallel_observations_symbol_signal_time_desc",
        "live_parallel_observations",
        ["symbol", sa.text("signal_time DESC")],
        unique=False,
    )
    op.create_index(
        "ix_live_parallel_observations_dry_run_status",
        "live_parallel_observations",
        ["dry_run_status"],
        unique=False,
    )
    op.create_index(
        "ix_live_parallel_observations_guard_passed",
        "live_parallel_observations",
        ["guard_passed"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_live_parallel_observations_guard_passed", table_name="live_parallel_observations")
    op.drop_index("ix_live_parallel_observations_dry_run_status", table_name="live_parallel_observations")
    op.drop_index("ix_live_parallel_observations_symbol_signal_time_desc", table_name="live_parallel_observations")
    op.drop_index("ix_live_parallel_observations_signal_time_desc", table_name="live_parallel_observations")
    op.drop_table("live_parallel_observations")
