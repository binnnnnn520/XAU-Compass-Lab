from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UTCDateTime, utcnow


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_signal_time_desc", text("signal_time DESC")),
        Index("ix_signals_strategy_run_id_signal_time_desc", "strategy_run_id", text("signal_time DESC")),
        Index("ix_signals_direction_signal_time_desc", "direction", text("signal_time DESC")),
        Index("ix_signals_source_type", "source_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    strategy_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_runs.id"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="XAUUSD",
        server_default=text("'XAUUSD'"),
    )
    signal_time: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    strength: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0"),
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0"),
    )
    price_at_signal: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    features_used: Mapped[dict[str, Any]] = mapped_column(
        JSONB(),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    reasoning: Mapped[str] = mapped_column(Text(), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="live",
        server_default=text("'live'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )

    strategy_run = relationship("StrategyRun", back_populates="signals")
    paper_orders = relationship("PaperOrder", back_populates="signal")
