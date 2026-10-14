from __future__ import annotations

from decimal import Decimal

from app.services.broker.interface import AccountData, BrokerInterface, OrderResult, PositionData


class MT5Broker(BrokerInterface):
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
        raise NotImplementedError("MT5 live broker integration is blocked until Phase 5 readiness.")

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError("MT5 live broker integration is blocked until Phase 5 readiness.")

    def get_positions(self) -> list[PositionData]:
        raise NotImplementedError("MT5 live broker integration is blocked until Phase 5 readiness.")

    def get_account(self) -> AccountData:
        raise NotImplementedError("MT5 live broker integration is blocked until Phase 5 readiness.")
