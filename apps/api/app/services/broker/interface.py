from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: str
    accepted: bool
    message: str | None = None


@dataclass(frozen=True)
class PositionData:
    position_id: str
    symbol: str
    side: str
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal | None
    status: str


@dataclass(frozen=True)
class AccountData:
    total_equity: Decimal
    cash: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    open_positions: int


class BrokerInterface(ABC):
    @abstractmethod
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
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    @abstractmethod
    def get_positions(self) -> list[PositionData]:
        ...

    @abstractmethod
    def get_account(self) -> AccountData:
        ...
