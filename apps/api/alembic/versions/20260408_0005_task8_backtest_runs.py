from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260408_0005"
down_revision = "20260402_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("initial_capital", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("final_capital", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("total_return", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("max_drawdown", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("win_rate", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["strategy_run_id"],
            ["strategy_runs.id"],
            name="fk_backtest_runs_strategy_run_id_strategy_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_runs"),
    )
    op.create_index("ix_backtest_runs_strategy_run_id", "backtest_runs", ["strategy_run_id"], unique=False)
    op.create_index("ix_backtest_runs_status", "backtest_runs", ["status"], unique=False)
    op.execute("CREATE INDEX ix_backtest_runs_created_at_desc ON backtest_runs (created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_backtest_runs_created_at_desc")
    op.drop_index("ix_backtest_runs_status", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_strategy_run_id", table_name="backtest_runs")
    op.drop_table("backtest_runs")
