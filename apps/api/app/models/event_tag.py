from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UTCDateTime, utcnow


class EventTag(Base):
    __tablename__ = "event_tags"
    __table_args__ = (
        UniqueConstraint("news_id", "tag_type", "tag_value", name="uq_event_tags_news_id_tag_type_tag_value"),
        Index("ix_event_tags_news_id", "news_id"),
        Index("ix_event_tags_tag_type_created_at_desc", "tag_type", text("created_at DESC")),
        Index("ix_event_tags_tag_value", "tag_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    news_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("news_items.id"),
        nullable=False,
    )
    tag_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tag_value: Mapped[str] = mapped_column(String(200), nullable=False)
    relevance_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("1.0000"),
        server_default=text("1.0"),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB(),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )

    news_item = relationship("NewsItem", back_populates="event_tags")
