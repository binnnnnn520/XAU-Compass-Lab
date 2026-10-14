from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import CheckConstraint, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.database import Base, UTCDateTime, utcnow


ECONOMIC_EVENT_IMPORTANCE_VALUES = ("low", "medium", "high")


class EconomicEvent(Base):
    __tablename__ = "economic_events"
    __table_args__ = (
        CheckConstraint(
            "importance IN ('low', 'medium', 'high')",
            name="economic_event_importance",
        ),
        Index("ix_economic_events_event_time_desc", text("event_time DESC")),
        Index("ix_economic_events_type_event_time_desc", "event_type", text("event_time DESC")),
        Index("ix_economic_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    event_time: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    importance: Mapped[str] = mapped_column(String(20), nullable=False, default="medium", server_default=text("'medium'"))
    currency: Mapped[Optional[str]] = mapped_column(String(10))
    actual_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    forecast_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    previous_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
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

    @validates("importance")
    def validate_importance(self, key: str, value: str) -> str:
        if value not in ECONOMIC_EVENT_IMPORTANCE_VALUES:
            allowed = ", ".join(ECONOMIC_EVENT_IMPORTANCE_VALUES)
            raise ValueError(f"importance must be one of: {allowed}")
        return value
