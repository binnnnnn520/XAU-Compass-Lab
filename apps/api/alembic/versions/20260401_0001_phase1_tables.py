from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260401_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "news_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("health_status", sa.String(length=20), nullable=False, server_default=sa.text("'healthy'")),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetch_interval", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id", name="pk_news_sources"),
    )
    op.create_index(
        "ix_news_sources_is_active_health_status",
        "news_sources",
        ["is_active", "health_status"],
        unique=False,
    )
    op.create_index("ix_news_sources_source_type", "news_sources", ["source_type"], unique=False)

    op.create_table(
        "news_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("title_hash", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False, server_default=sa.text("'en'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["source_id"], ["news_sources.id"], name="fk_news_items_source_id_news_sources"),
        sa.PrimaryKeyConstraint("id", name="pk_news_items"),
        sa.UniqueConstraint("title_hash", "source_id", name="uq_news_items_title_hash_source_id"),
    )
    op.execute("CREATE INDEX ix_news_items_published_at_desc ON news_items (published_at DESC)")
    op.create_index("ix_news_items_status", "news_items", ["status"], unique=False)
    op.execute("CREATE INDEX ix_news_items_source_id_published_at_desc ON news_items (source_id, published_at DESC)")

    op.create_table(
        "market_bars",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("symbol", sa.String(length=20), nullable=False, server_default=sa.text("'XAUUSD'")),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("bar_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("volume", sa.Numeric(precision=20, scale=8), nullable=False, server_default=sa.text("0")),
        sa.Column("data_source", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id", name="pk_market_bars"),
        sa.UniqueConstraint("symbol", "timeframe", "bar_time", name="uq_market_bars_symbol_timeframe_bar_time"),
    )
    op.execute(
        "CREATE INDEX ix_market_bars_symbol_timeframe_bar_time_desc "
        "ON market_bars (symbol, timeframe, bar_time DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_market_bars_symbol_timeframe_bar_time_desc")
    op.drop_table("market_bars")

    op.execute("DROP INDEX IF EXISTS ix_news_items_source_id_published_at_desc")
    op.drop_index("ix_news_items_status", table_name="news_items")
    op.execute("DROP INDEX IF EXISTS ix_news_items_published_at_desc")
    op.drop_table("news_items")

    op.drop_index("ix_news_sources_source_type", table_name="news_sources")
    op.drop_index("ix_news_sources_is_active_health_status", table_name="news_sources")
    op.drop_table("news_sources")
