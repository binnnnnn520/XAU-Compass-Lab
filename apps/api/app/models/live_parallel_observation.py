from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, utcnow


class LiveParallelObservation(Base):
    __tablename__ = "live_parallel_observations"
    __table_args__ = (
        Index("ix_live_parallel_observations_signal_time_desc", text("signal_time DESC")),
        Index("ix_live_parallel_observations_symbol_signal_time_desc", "symbol", text("signal_time DESC")),
        Index("ix_live_parallel_observations_dry_run_status", "dry_run_status"),
        Index("ix_live_parallel_observations_guard_passed", "guard_passed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    signal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="XAUUSD",
        server_default=text("'XAUUSD'"),
    )
    signal_time: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    paper_direction: Mapped[str] = mapped_column(String(10), nullable=False)
    live_direction: Mapped[str] = mapped_column(String(10), nullable=False)
    paper_order_time: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    live_order_time: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    paper_fill_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    live_fill_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    order_notional: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    dry_run_status: Mapped[str] = mapped_column(String(20), nullable=False)
    guard_passed: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    risk_event_count: Mapped[int] = mapped_column(
        Integer(),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB(),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )
