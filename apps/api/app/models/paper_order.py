from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UTCDateTime, utcnow


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        Index("ix_paper_orders_signal_id", "signal_id"),
        Index("ix_paper_orders_status", "status"),
        Index("ix_paper_orders_created_at_desc", text("created_at DESC")),
        Index("ix_paper_orders_symbol_created_at_desc", "symbol", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("signals.id"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="XAUUSD",
        server_default=text("'XAUUSD'"),
    )
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="MARKET",
        server_default=text("'MARKET'"),
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    slippage: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal("0"),
        server_default=text("0"),
    )
    commission: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal("0"),
        server_default=text("0"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    reject_reason: Mapped[str | None] = mapped_column(Text())
    filled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        server_default=text("NOW()"),
    )

    signal = relationship("Signal", back_populates="paper_orders")
    entry_positions = relationship(
        "PaperPosition",
        back_populates="entry_order",
        foreign_keys="PaperPosition.entry_order_id",
    )
    exit_positions = relationship(
        "PaperPosition",
        back_populates="exit_order",
        foreign_keys="PaperPosition.exit_order_id",
    )
    risk_events = relationship("RiskEvent", back_populates="related_order")
