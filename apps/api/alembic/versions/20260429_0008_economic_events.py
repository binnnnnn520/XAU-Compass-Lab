from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260429_0008"
down_revision = "20260415_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "economic_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("importance", sa.String(length=20), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("actual_value", sa.Numeric(20, 8), nullable=True),
        sa.Column("forecast_value", sa.Numeric(20, 8), nullable=True),
        sa.Column("previous_value", sa.Numeric(20, 8), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "importance IN ('low', 'medium', 'high')",
            name=op.f("ck_economic_events_economic_event_importance"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_economic_events")),
    )
    op.create_index("ix_economic_events_event_time_desc", "economic_events", [sa.text("event_time DESC")])
    op.create_index(
        "ix_economic_events_type_event_time_desc",
        "economic_events",
        ["event_type", sa.text("event_time DESC")],
    )
    op.create_index(op.f("ix_economic_events_created_at"), "economic_events", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_economic_events_created_at"), table_name="economic_events")
    op.drop_index("ix_economic_events_type_event_time_desc", table_name="economic_events")
    op.drop_index("ix_economic_events_event_time_desc", table_name="economic_events")
    op.drop_table("economic_events")
