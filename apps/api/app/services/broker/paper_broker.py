from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PaperOrder, PaperPosition
from app.services.broker.interface import AccountData, BrokerInterface, OrderResult, PositionData
from app.services.paper_execution.service import _apply_fill, get_paper_account


class PaperBroker(BrokerInterface):
    def __init__(self, session: Session, *, signal_id: UUID | None = None, fill_time: datetime | None = None) -> None:
        self.session = session
        self.signal_id = signal_id
        self.fill_time = fill_time

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        order_type: str = "market",
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> OrderResult:
        if self.signal_id is None:
            raise ValueError("PaperBroker requires signal_id to persist paper orders.")
        if side not in {"BUY", "SELL"}:
            raise ValueError("PaperBroker side must be BUY or SELL.")

        fill_time = self.fill_time or datetime.now(UTC)
        order = PaperOrder(
            signal_id=self.signal_id,
            symbol=symbol,
            side=side,
            order_type=order_type.upper(),
            quantity=quantity,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="filled",
            filled_at=fill_time,
        )
        self.session.add(order)
        self.session.flush()
        _apply_fill(self.session, order=order, fill_time=fill_time)
        return OrderResult(order_id=str(order.id), status=order.status, accepted=True)

    def cancel_order(self, order_id: str) -> bool:
        order = self.session.get(PaperOrder, UUID(order_id))
        if order is None or order.status != "pending":
            return False
        order.status = "cancelled"
        self.session.add(order)
        self.session.flush()
        return True

    def get_positions(self) -> list[PositionData]:
        positions = self.session.execute(
            select(PaperPosition).order_by(PaperPosition.opened_at.asc(), PaperPosition.id.asc())
        ).scalars().all()
        return [
            PositionData(
                position_id=str(position.id),
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
                entry_price=position.entry_price,
                current_price=position.current_price,
                status=position.status,
            )
            for position in positions
        ]

    def get_account(self) -> AccountData:
        account = get_paper_account(self.session)
        return AccountData(
            total_equity=account.total_equity,
            cash=account.cash,
            unrealized_pnl=account.unrealized_pnl,
            realized_pnl=account.realized_pnl,
            open_positions=account.open_positions,
        )
