from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database import Base, UTCDateTime, utcnow


NEWS_ITEM_ALLOWED_STATUSES = ("pending", "analyzed", "failed")
NEWS_ITEM_STATUS_CHECK_CONSTRAINT = "news_item_status"


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("title_hash", "source_id", name="uq_news_items_title_hash_source_id"),
        CheckConstraint(
            "status IN ('pending', 'analyzed', 'failed')",
            name=NEWS_ITEM_STATUS_CHECK_CONSTRAINT,
        ),
        Index("ix_news_items_published_at_desc", text("published_at DESC")),
        Index("ix_news_items_status", "status"),
        Index("ix_news_items_source_id_published_at_desc", "source_id", text("published_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("news_sources.id"))
    title: Mapped[str] = mapped_column(Text(), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text())
    summary: Mapped[Optional[str]] = mapped_column(Text())
    url: Mapped[Optional[str]] = mapped_column(Text())
    author: Mapped[Optional[str]] = mapped_column(String(200))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
    title_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en", server_default=text("'en'"))
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    raw_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=text("NOW()"),
    )

    source = relationship("NewsSource", back_populates="items")
    sentiment_scores = relationship("SentimentScore", back_populates="news_item", cascade="all, delete-orphan")
    event_tags = relationship("EventTag", back_populates="news_item", cascade="all, delete-orphan")

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        if value not in NEWS_ITEM_ALLOWED_STATUSES:
            allowed = ", ".join(NEWS_ITEM_ALLOWED_STATUSES)
            raise ValueError(f"status must be one of: {allowed}")
        return value
