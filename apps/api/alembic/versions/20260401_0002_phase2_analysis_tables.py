from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260401_0002"
down_revision = "20260401_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sentiment_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("news_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analyzer_type", sa.String(length=30), nullable=False),
        sa.Column("sentiment", sa.String(length=10), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["news_id"], ["news_items.id"], name="fk_sentiment_scores_news_id_news_items"),
        sa.PrimaryKeyConstraint("id", name="pk_sentiment_scores"),
        sa.UniqueConstraint("news_id", "analyzer_type", name="uq_sentiment_scores_news_id_analyzer_type"),
    )
    op.create_index("ix_sentiment_scores_news_id", "sentiment_scores", ["news_id"], unique=False)
    op.execute("CREATE INDEX ix_sentiment_scores_created_at_desc ON sentiment_scores (created_at DESC)")
    op.execute(
        "CREATE INDEX ix_sentiment_scores_sentiment_created_at_desc "
        "ON sentiment_scores (sentiment, created_at DESC)"
    )

    op.create_table(
        "event_tags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("news_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_type", sa.String(length=50), nullable=False),
        sa.Column("tag_value", sa.String(length=200), nullable=False),
        sa.Column("relevance_score", sa.Numeric(precision=5, scale=4), nullable=False, server_default=sa.text("1.0")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["news_id"], ["news_items.id"], name="fk_event_tags_news_id_news_items"),
        sa.PrimaryKeyConstraint("id", name="pk_event_tags"),
        sa.UniqueConstraint("news_id", "tag_type", "tag_value", name="uq_event_tags_news_id_tag_type_tag_value"),
    )
    op.create_index("ix_event_tags_news_id", "event_tags", ["news_id"], unique=False)
    op.execute("CREATE INDEX ix_event_tags_tag_type_created_at_desc ON event_tags (tag_type, created_at DESC)")
    op.create_index("ix_event_tags_tag_value", "event_tags", ["tag_value"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_event_tags_tag_value", table_name="event_tags")
    op.execute("DROP INDEX IF EXISTS ix_event_tags_tag_type_created_at_desc")
    op.drop_index("ix_event_tags_news_id", table_name="event_tags")
    op.drop_table("event_tags")

    op.execute("DROP INDEX IF EXISTS ix_sentiment_scores_sentiment_created_at_desc")
    op.execute("DROP INDEX IF EXISTS ix_sentiment_scores_created_at_desc")
    op.drop_index("ix_sentiment_scores_news_id", table_name="sentiment_scores")
    op.drop_table("sentiment_scores")
