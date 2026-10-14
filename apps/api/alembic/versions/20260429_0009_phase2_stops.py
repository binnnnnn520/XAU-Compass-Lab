from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260429_0009"
down_revision = "20260429_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_orders", sa.Column("stop_loss", sa.Numeric(precision=20, scale=8), nullable=True))
    op.add_column("paper_orders", sa.Column("take_profit", sa.Numeric(precision=20, scale=8), nullable=True))
    op.add_column("paper_positions", sa.Column("stop_loss", sa.Numeric(precision=20, scale=8), nullable=True))
    op.add_column("paper_positions", sa.Column("take_profit", sa.Numeric(precision=20, scale=8), nullable=True))
    op.add_column(
        "paper_positions",
        sa.Column("trailing_stop_distance", sa.Numeric(precision=20, scale=8), nullable=True),
    )
    op.add_column(
        "paper_positions",
        sa.Column("trailing_stop_price", sa.Numeric(precision=20, scale=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_positions", "trailing_stop_price")
    op.drop_column("paper_positions", "trailing_stop_distance")
    op.drop_column("paper_positions", "take_profit")
    op.drop_column("paper_positions", "stop_loss")
    op.drop_column("paper_orders", "take_profit")
    op.drop_column("paper_orders", "stop_loss")
