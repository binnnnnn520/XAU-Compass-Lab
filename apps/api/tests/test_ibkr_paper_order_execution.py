from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.services.broker import IBKRPaperSandboxBroker
from app.services.live_readiness import (
    LiveBrokerRoutingRequest,
    LiveOrderRequest,
    load_live_readiness_config,
)


class FakeExecutionClient:
    def __init__(self) -> None:
        self.health_checks: list[dict[str, str]] = []
        self.account_snapshots: list[dict[str, str]] = []
        self.orders: list[dict[str, str]] = []
        self.cancellations: list[tuple[str, dict[str, str]]] = []
        self.positions: list[dict[str, str]] = [
            {
                "position_id": "paper-position-1",
                "symbol": "XAUUSD",
                "side": "LONG",
                "quantity": "0.10000000",
                "entry_price": "2300.00000000",
                "status": "open",
            }
        ]

    def check_connection(self, payload: dict[str, str]) -> dict[str, str]:
        self.health_checks.append(payload)
        return {"server_time": "2026-05-01T11:00:00+00:00", "server_version": "paper"}

    def get_account_snapshot(self, payload: dict[str, str]) -> dict[str, str]:
        self.account_snapshots.append(payload)
        return {
            "net_liquidation": "100000.00000000",
            "cash": "50000.00000000",
            "buying_power": "50000.00000000",
            "unrealized_pnl": "0.00000000",
            "realized_pnl": "0.00000000",
            "currency": "USD",
        }

    def place_order(self, payload: dict[str, str]):
        self.orders.append(payload)
        return {
            "order_id": f"ibkr-paper-{len(self.orders)}",
            "status": "submitted",
            "accepted": True,
            "message": None,
        }

    def cancel_order(self, order_id: str, payload: dict[str, str]) -> bool:
        self.cancellations.append((order_id, payload))
        return True

    def get_positions(self, payload: dict[str, str]) -> list[dict[str, str]]:
        return self.positions


class DelayedPositionExecutionClient(FakeExecutionClient):
    def __init__(self) -> None:
        super().__init__()
        self.position_checks = 0

    def get_positions(self, payload: dict[str, str]) -> list[dict[str, str]]:
        self.position_checks += 1
        if self.position_checks == 1:
            return []
        return self.positions


def _ibkr_env(*, mode: str = "paper") -> dict[str, str]:
    return {
        "IBKR_PAPER_SANDBOX_MODE": mode,
        "IBKR_PAPER_SANDBOX_HOST": "127.0.0.1",
        "IBKR_PAPER_SANDBOX_PORT": "7497",
        "IBKR_PAPER_SANDBOX_CLIENT_ID": "101",
        "IBKR_PAPER_SANDBOX_ACCOUNT_ID": "DU123456",
    }


def _ibkr_env_with_contract() -> dict[str, str]:
    return {
        **_ibkr_env(),
        "IBKR_PAPER_ORDER_SEC_TYPE": "CMDTY",
        "IBKR_PAPER_ORDER_EXCHANGE": "SMART",
        "IBKR_PAPER_ORDER_CURRENCY": "USD",
        "IBKR_PAPER_ORDER_PRIMARY_EXCHANGE": "NYSE",
    }


def _live_config(*, routing_enabled: bool = True, daily_notional_limit: str = "10000.00000000"):
    return load_live_readiness_config(
        {
            "live": {
                "enabled": True,
                "kill_switch_enabled": False,
                "daily_notional_limit": daily_notional_limit,
                "max_initial_capital_fraction": "0.0100",
                "real_broker_routing_enabled": routing_enabled,
            }
        }
    )


def _order_request() -> LiveOrderRequest:
    return LiveOrderRequest(
        symbol="XAUUSD",
        side="BUY",
        quantity=Decimal("0.10000000"),
        price=Decimal("2300.00000000"),
        confidence=Decimal("0.9500"),
        daily_notional_so_far=Decimal("0.00000000"),
        total_equity=Decimal("100000.00000000"),
    )


def _approval() -> LiveBrokerRoutingRequest:
    return LiveBrokerRoutingRequest(
        broker_name="ibkr",
        credentials_configured=True,
        manual_approval_id="approval-phase5-17",
        approval_actor="phase5_admin",
        approved_at=datetime(2026, 5, 1, 11, 0, tzinfo=UTC),
    )


def test_ibkr_paper_order_execution_is_disabled_by_default() -> None:
    client = FakeExecutionClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=False,
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approval(),
        submitted_at=datetime(2026, 5, 1, 11, 1, tzinfo=UTC),
    )

    assert result.accepted is False
    assert result.reject_reason == "paper_order_execution_disabled"
    assert result.lifecycle == ["rejected"]
    assert client.orders == []
    assert client.cancellations == []


def test_ibkr_paper_order_execution_rejects_non_paper_mode_without_client_call() -> None:
    client = FakeExecutionClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env(mode="live"))

    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=True,
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approval(),
        submitted_at=datetime(2026, 5, 1, 11, 2, tzinfo=UTC),
    )

    assert result.accepted is False
    assert result.reject_reason == "paper_sandbox_mode_required"
    assert client.health_checks == []
    assert client.orders == []


def test_ibkr_paper_order_execution_skips_client_when_readiness_fails() -> None:
    client = FakeExecutionClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=True,
        config=_live_config(daily_notional_limit="100.00000000"),
        order_request=_order_request(),
        routing_request=_approval(),
        submitted_at=datetime(2026, 5, 1, 11, 3, tzinfo=UTC),
    )

    assert result.accepted is False
    assert result.reject_reason == "daily_notional_limit_exceeded"
    assert client.health_checks == []
    assert client.orders == []


def test_ibkr_paper_order_execution_skips_client_when_routing_disabled() -> None:
    client = FakeExecutionClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=True,
        config=_live_config(routing_enabled=False),
        order_request=_order_request(),
        routing_request=_approval(),
        submitted_at=datetime(2026, 5, 1, 11, 4, tzinfo=UTC),
    )

    assert result.accepted is False
    assert result.reject_reason == "real_broker_routing_disabled"
    assert client.health_checks == []
    assert client.orders == []


def test_ibkr_paper_order_execution_skips_client_without_manual_approval() -> None:
    client = FakeExecutionClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())
    missing_approval = LiveBrokerRoutingRequest(
        broker_name="ibkr",
        credentials_configured=True,
        manual_approval_id=None,
        approval_actor=None,
        approved_at=None,
    )

    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=True,
        config=_live_config(),
        order_request=_order_request(),
        routing_request=missing_approval,
        submitted_at=datetime(2026, 5, 1, 11, 5, tzinfo=UTC),
    )

    assert result.accepted is False
    assert result.reject_reason == "manual_approval_missing"
    assert client.health_checks == []
    assert client.orders == []


def test_ibkr_paper_order_execution_calls_submit_cancel_and_close_after_all_guards_pass() -> None:
    client = FakeExecutionClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())
    submitted_at = datetime(2026, 5, 1, 11, 6, tzinfo=UTC)
    cancel_requested_at = datetime(2026, 5, 1, 11, 7, tzinfo=UTC)

    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=True,
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approval(),
        submitted_at=submitted_at,
        cancel_requested_at=cancel_requested_at,
        close_existing_position=True,
    )

    assert result.accepted is True
    assert result.status == "closed"
    assert result.submitted_order_id == "ibkr-paper-1"
    assert result.close_order_id == "ibkr-paper-2"
    assert result.cancelled is True
    assert result.lifecycle == ["submitted", "cancel_requested", "cancelled", "close_submitted"]
    assert client.health_checks != []
    assert client.account_snapshots != []
    assert client.orders == [
        {
            "account_id": "DU123456",
            "symbol": "XAUUSD",
            "side": "BUY",
            "quantity": "0.10000000",
            "price": "2300.00000000",
            "order_type": "limit",
            "manual_approval_id": "approval-phase5-17",
            "approval_actor": "phase5_admin",
            "approved_at": "2026-05-01T11:00:00+00:00",
            "order_role": "entry_verification",
        },
        {
            "account_id": "DU123456",
            "symbol": "XAUUSD",
            "side": "SELL",
            "quantity": "0.10000000",
            "price": "2300.00000000",
            "order_type": "market",
            "manual_approval_id": "approval-phase5-17",
            "approval_actor": "phase5_admin",
            "approved_at": "2026-05-01T11:00:00+00:00",
            "order_role": "close_position",
        },
    ]
    assert client.cancellations == [
        (
            "ibkr-paper-1",
            {
                "account_id": "DU123456",
                "manual_approval_id": "approval-phase5-17",
                "approval_actor": "phase5_admin",
                "cancel_requested_at": "2026-05-01T11:07:00+00:00",
            },
        )
    ]


def test_ibkr_paper_order_execution_skips_close_when_no_matching_position() -> None:
    client = FakeExecutionClient()
    client.positions = []
    broker = IBKRPaperSandboxBroker(
        client=client,
        environ={**_ibkr_env(), "IBKR_PAPER_POSITION_CONFIRMATION_ATTEMPTS": "1"},
    )

    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=True,
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approval(),
        submitted_at=datetime(2026, 5, 1, 11, 7, tzinfo=UTC),
        close_existing_position=True,
    )

    assert result.accepted is True
    assert result.close_order_id is None
    assert result.lifecycle == ["submitted", "close_skipped_no_position"]
    assert len(client.orders) == 1


def test_ibkr_paper_order_execution_waits_for_new_position_before_close() -> None:
    client = DelayedPositionExecutionClient()
    broker = IBKRPaperSandboxBroker(
        client=client,
        environ={
            **_ibkr_env(),
            "IBKR_PAPER_POSITION_CONFIRMATION_ATTEMPTS": "2",
            "IBKR_PAPER_POSITION_CONFIRMATION_SLEEP_SECONDS": "0",
        },
    )

    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=True,
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approval(),
        submitted_at=datetime(2026, 5, 1, 11, 7, tzinfo=UTC),
        close_existing_position=True,
        order_type="market",
    )

    assert result.accepted is True
    assert result.status == "closed"
    assert result.close_order_id == "ibkr-paper-2"
    assert result.lifecycle == ["submitted", "close_submitted"]
    assert client.position_checks == 2


def test_ibkr_paper_order_execution_passes_env_contract_fields_to_client() -> None:
    client = FakeExecutionClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env_with_contract())

    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=True,
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approval(),
        submitted_at=datetime(2026, 5, 1, 11, 8, tzinfo=UTC),
    )

    assert result.accepted is True
    assert client.orders[0]["sec_type"] == "CMDTY"
    assert client.orders[0]["exchange"] == "SMART"
    assert client.orders[0]["currency"] == "USD"
    assert client.orders[0]["primary_exchange"] == "NYSE"


def test_ibkr_paper_order_execution_rejects_naive_timestamps() -> None:
    broker = IBKRPaperSandboxBroker(client=FakeExecutionClient(), environ=_ibkr_env())

    try:
        broker.execute_paper_order_lifecycle_if_allowed(
            execution_enabled=True,
            config=_live_config(),
            order_request=_order_request(),
            routing_request=_approval(),
            submitted_at=datetime(2026, 5, 1, 11, 8),
        )
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive IBKR paper order execution timestamps must be rejected")
