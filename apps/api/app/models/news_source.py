from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UTCDateTime, utcnow


class NewsSource(Base):
    __tablename__ = "news_sources"
    __table_args__ = (
        Index("ix_news_sources_is_active_health_status", "is_active", "health_status"),
        Index("ix_news_sources_source_type", "source_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str] = mapped_column(Text(), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB(),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    health_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="healthy",
        server_default=text("'healthy'"),
    )
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    fetch_interval: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        default=300,
        server_default=text("300"),
    )
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

    items = relationship("NewsItem", back_populates="source")
