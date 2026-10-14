from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260401_0003"
down_revision = "20260401_0002"
branch_labels = None
depends_on = None

ALLOWED_STATUSES = ("pending", "analyzed", "failed")
STATUS_CHECK_CONSTRAINT = "news_item_status"


def upgrade() -> None:
    bind = op.get_bind()
    invalid_statuses = bind.execute(
        sa.text(
            """
            SELECT DISTINCT status
            FROM news_items
            WHERE status NOT IN ('pending', 'analyzed', 'failed')
            ORDER BY status
            """
        )
    ).scalars().all()
    if invalid_statuses:
        invalid_values = ", ".join(invalid_statuses)
        raise RuntimeError(f"news_items.status contains invalid values: {invalid_values}")

    op.create_check_constraint(
        STATUS_CHECK_CONSTRAINT,
        "news_items",
        "status IN ('pending', 'analyzed', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(STATUS_CHECK_CONSTRAINT, "news_items", type_="check")
