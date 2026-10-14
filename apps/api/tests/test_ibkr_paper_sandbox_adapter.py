from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import sys


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.broker import (
    IBKRPaperSandboxBroker,
    IBKRPaperSandboxCredentials,
    IBKRPaperSandboxIBAPIClient,
    OrderResult,
)
from app.services.broker.ibkr_broker import _IBKRPaperSandboxIBAPIApp
from app.services.live_readiness import (
    LiveBrokerRoutingRequest,
    LiveOrderRequest,
    load_live_readiness_config,
)


class FakeIBKRClient:
    def __init__(self) -> None:
        self.orders: list[dict[str, str]] = []
        self.health_checks: list[dict[str, str]] = []
        self.account_snapshots: list[dict[str, str]] = []

    def place_order(self, payload: dict[str, str]) -> OrderResult:
        self.orders.append(payload)
        return OrderResult(order_id="ibkr-paper-1", status="submitted", accepted=True)

    def check_connection(self, payload: dict[str, str]) -> dict[str, str]:
        self.health_checks.append(payload)
        return {
            "server_time": "2026-05-01T00:00:00+00:00",
            "server_version": "paper-sandbox",
        }

    def get_account_snapshot(self, payload: dict[str, str]) -> dict[str, str]:
        self.account_snapshots.append(payload)
        return {
            "net_liquidation": "100000.12345678",
            "cash": "25000.00000000",
            "buying_power": "50000.00000000",
            "unrealized_pnl": "-12.34000000",
            "realized_pnl": "100.01000000",
            "currency": "USD",
            "account_id": "DU123456",
        }


class FailingIBKRClient(FakeIBKRClient):
    def check_connection(self, payload: dict[str, str]) -> dict[str, str]:
        self.health_checks.append(payload)
        raise RuntimeError("auth failed for account DU123456 with token SECRET")


class FailingAccountIBKRClient(FakeIBKRClient):
    def get_account_snapshot(self, payload: dict[str, str]) -> dict[str, str]:
        self.account_snapshots.append(payload)
        raise RuntimeError("account DU123456 rejected token SECRET")


class FakeIBAPIApp:
    def __init__(self, *, account_id: str = "DU123456") -> None:
        self.account_id = account_id
        self.connection_checks: list[dict[str, object]] = []
        self.account_summary_requests: list[dict[str, object]] = []
        self.placed_orders: list[dict[str, object]] = []
        self.cancelled_orders: list[dict[str, object]] = []
        self.disconnected = False

    def connect_and_check(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
    ) -> dict[str, str]:
        self.connection_checks.append(
            {
                "host": host,
                "port": port,
                "client_id": client_id,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "server_time": "2026-05-01T05:00:00+00:00",
            "server_version": "178",
        }

    def get_account_summary(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
    ) -> dict[str, str]:
        self.account_summary_requests.append(
            {
                "host": host,
                "port": port,
                "client_id": client_id,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "account_id": self.account_id,
            "net_liquidation": "100000.12345678",
            "cash": "25000.00000000",
            "buying_power": "50000.00000000",
            "unrealized_pnl": "-12.34000000",
            "realized_pnl": "100.01000000",
            "currency": "USD",
        }

    def get_positions(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
    ) -> list[dict[str, str]]:
        return [
            {
                "account_id": self.account_id,
                "symbol": "AAPL",
                "quantity": "1.00000000",
                "entry_price": "180.00000000",
                "status": "open",
            }
        ]

    def disconnect(self) -> None:
        self.disconnected = True

    def place_order(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
        payload: dict[str, str],
    ) -> dict[str, str]:
        self.placed_orders.append(
            {
                "host": host,
                "port": port,
                "client_id": client_id,
                "timeout_seconds": timeout_seconds,
                "payload": payload,
            }
        )
        return {"order_id": "9001", "status": "Submitted", "accepted": "true"}

    def cancel_order(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
        order_id: str,
    ) -> bool:
        self.cancelled_orders.append(
            {
                "host": host,
                "port": port,
                "client_id": client_id,
                "timeout_seconds": timeout_seconds,
                "order_id": order_id,
            }
        )
        return True


class MissingPnlIBAPIApp(FakeIBAPIApp):
    def get_account_summary(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
    ) -> dict[str, str]:
        snapshot = super().get_account_summary(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=timeout_seconds,
        )
        snapshot.pop("unrealized_pnl")
        snapshot.pop("realized_pnl")
        return snapshot


class RejectedOrderIBAPIApp(FakeIBAPIApp):
    def place_order(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
        payload: dict[str, str],
    ) -> dict[str, str]:
        super().place_order(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=timeout_seconds,
            payload=payload,
        )
        return {"order_id": "9002", "status": "Error:321", "accepted": "false"}


def _ibkr_env() -> dict[str, str]:
    return {
        "IBKR_PAPER_SANDBOX_MODE": "paper",
        "IBKR_PAPER_SANDBOX_HOST": "127.0.0.1",
        "IBKR_PAPER_SANDBOX_PORT": "7497",
        "IBKR_PAPER_SANDBOX_CLIENT_ID": "101",
        "IBKR_PAPER_SANDBOX_ACCOUNT_ID": "DU123456",
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


def _approved_request() -> LiveBrokerRoutingRequest:
    return LiveBrokerRoutingRequest(
        broker_name="ibkr",
        credentials_configured=True,
        manual_approval_id="approval-ibkr-paper-1",
        approval_actor="phase5_admin",
        approved_at=datetime(2026, 4, 30, 8, 30, tzinfo=UTC),
    )


def test_ibkr_paper_ibapi_client_connection_report_uses_payload_without_secrets() -> None:
    app = FakeIBAPIApp()
    client = IBKRPaperSandboxIBAPIClient(
        app_factory=lambda: app,
        timeout_seconds=Decimal("1.5000"),
    )

    report = client.check_connection(
        {
            "host": "127.0.0.1",
            "port": "4002",
            "client_id": "101",
            "mode": "paper",
            "account_id": "DU123456",
        }
    )

    assert report == {
        "server_time": "2026-05-01T05:00:00+00:00",
        "server_version": "178",
    }
    assert app.connection_checks == [
        {
            "host": "127.0.0.1",
            "port": 4002,
            "client_id": 101,
            "timeout_seconds": Decimal("1.5000"),
        }
    ]
    assert app.disconnected is True
    assert "DU123456" not in str(report)


def test_ibkr_paper_ibapi_client_applies_configured_reconnect_cooldown() -> None:
    app = FakeIBAPIApp()
    cooldowns: list[float] = []
    client = IBKRPaperSandboxIBAPIClient(
        app_factory=lambda: app,
        timeout_seconds=Decimal("1.5000"),
        reconnect_cooldown_seconds=Decimal("1.2500"),
        sleeper=cooldowns.append,
    )

    client.check_connection(
        {
            "host": "127.0.0.1",
            "port": "4002",
            "client_id": "101",
            "mode": "paper",
            "account_id": "DU123456",
        }
    )

    assert cooldowns == [1.25]
    assert app.disconnected is True


def test_ibkr_paper_ibapi_client_account_snapshot_filters_account_and_decimal_strings() -> None:
    app = FakeIBAPIApp(account_id="DU123456")
    client = IBKRPaperSandboxIBAPIClient(
        app_factory=lambda: app,
        expected_account_id="DU123456",
        timeout_seconds=Decimal("2.0000"),
    )

    snapshot = client.get_account_snapshot(
        {
            "host": "127.0.0.1",
            "port": "4002",
            "client_id": "101",
            "mode": "paper",
        }
    )

    assert snapshot == {
        "net_liquidation": "100000.12345678",
        "cash": "25000.00000000",
        "buying_power": "50000.00000000",
        "unrealized_pnl": "-12.34000000",
        "realized_pnl": "100.01000000",
        "currency": "USD",
    }
    assert app.account_summary_requests == [
        {
            "host": "127.0.0.1",
            "port": 4002,
            "client_id": 101,
            "timeout_seconds": Decimal("2.0000"),
        }
    ]
    assert app.disconnected is True
    assert "DU123456" not in str(snapshot)


def test_ibkr_paper_ibapi_client_defaults_missing_pnl_fields_to_decimal_zero() -> None:
    app = MissingPnlIBAPIApp(account_id="DU123456")
    client = IBKRPaperSandboxIBAPIClient(
        app_factory=lambda: app,
        expected_account_id="DU123456",
    )

    snapshot = client.get_account_snapshot(
        {
            "host": "127.0.0.1",
            "port": "4002",
            "client_id": "101",
            "mode": "paper",
        }
    )

    assert snapshot["unrealized_pnl"] == "0.00000000"
    assert snapshot["realized_pnl"] == "0.00000000"


def test_ibkr_paper_ibapi_client_rejects_account_mismatch_without_leaking_ids() -> None:
    app = FakeIBAPIApp(account_id="DU999999")
    client = IBKRPaperSandboxIBAPIClient(
        app_factory=lambda: app,
        expected_account_id="DU123456",
    )

    try:
        client.get_account_snapshot(
            {
                "host": "127.0.0.1",
                "port": "4002",
                "client_id": "101",
                "mode": "paper",
            }
        )
    except RuntimeError as exc:
        assert str(exc) == "ibkr_paper_account_mismatch"
    else:
        raise AssertionError("IBKR paper account mismatches must be rejected")

    assert app.disconnected is True


def test_ibkr_paper_ibapi_client_positions_filter_account_and_hide_account_id() -> None:
    app = FakeIBAPIApp(account_id="DU123456")
    client = IBKRPaperSandboxIBAPIClient(
        app_factory=lambda: app,
        expected_account_id="DU123456",
        timeout_seconds=Decimal("2.0000"),
    )

    positions = client.get_positions(
        {
            "host": "127.0.0.1",
            "port": "4002",
            "client_id": "101",
            "mode": "paper",
        }
    )

    assert positions == [
        {
            "symbol": "AAPL",
            "quantity": "1.00000000",
            "entry_price": "180.00000000",
            "status": "open",
        }
    ]
    assert app.disconnected is True
    assert "DU123456" not in str(positions)


def test_ibkr_paper_ibapi_client_positions_use_configured_credentials() -> None:
    app = FakeIBAPIApp(account_id="DU123456")
    client = IBKRPaperSandboxIBAPIClient(
        app_factory=lambda: app,
        credentials=IBKRPaperSandboxCredentials(
            host="127.0.0.1",
            port=4002,
            client_id=101,
            account_id="DU123456",
            mode="paper",
        ),
        expected_account_id="DU123456",
        timeout_seconds=Decimal("2.0000"),
    )

    positions = client.get_positions({"account_id": "DU123456", "symbol": "AAPL"})

    assert positions[0]["symbol"] == "AAPL"
    assert app.disconnected is True


def test_ibkr_paper_ibapi_client_disables_order_execution_by_default() -> None:
    client = IBKRPaperSandboxIBAPIClient(app_factory=FakeIBAPIApp)

    try:
        client.place_order({"symbol": "XAUUSD"})
    except NotImplementedError as exc:
        assert "disabled by default" in str(exc)
    else:
        raise AssertionError("IBKR paper ibapi client must not place orders by default")


def test_ibkr_paper_ibapi_client_places_and_cancels_orders_only_when_enabled() -> None:
    app = FakeIBAPIApp()
    client = IBKRPaperSandboxIBAPIClient(
        app_factory=lambda: app,
        credentials=IBKRPaperSandboxCredentials(
            host="127.0.0.1",
            port=4002,
            client_id=101,
            account_id="DU123456",
        ),
        order_execution_enabled=True,
        timeout_seconds=Decimal("2.0000"),
    )

    result = client.place_order(
        {
            "symbol": "XAUUSD",
            "side": "BUY",
            "quantity": "0.10000000",
            "price": "2300.00000000",
            "order_type": "limit",
            "sec_type": "CMDTY",
            "exchange": "SMART",
            "currency": "USD",
        }
    )
    cancelled = client.cancel_order("9001", {"manual_approval_id": "approval-1"})

    assert result == OrderResult(order_id="9001", status="Submitted", accepted=True)
    assert cancelled is True
    assert app.placed_orders == [
        {
            "host": "127.0.0.1",
            "port": 4002,
            "client_id": 101,
            "timeout_seconds": Decimal("2.0000"),
            "payload": {
                "symbol": "XAUUSD",
                "side": "BUY",
                "quantity": "0.10000000",
                "price": "2300.00000000",
                "order_type": "limit",
                "sec_type": "CMDTY",
                "exchange": "SMART",
                "currency": "USD",
            },
        }
    ]
    assert app.cancelled_orders == [
        {
            "host": "127.0.0.1",
            "port": 4002,
            "client_id": 101,
            "timeout_seconds": Decimal("2.0000"),
            "order_id": "9001",
        }
    ]
    assert app.disconnected is True


def test_ibkr_paper_ibapi_client_preserves_string_false_order_rejection() -> None:
    client = IBKRPaperSandboxIBAPIClient(
        app_factory=RejectedOrderIBAPIApp,
        credentials=IBKRPaperSandboxCredentials(
            host="127.0.0.1",
            port=4002,
            client_id=101,
            account_id="DU123456",
        ),
        order_execution_enabled=True,
    )

    result = client.place_order(
        {
            "symbol": "XAUUSD",
            "side": "BUY",
            "quantity": "0.10000000",
            "price": "2300.00000000",
            "order_type": "limit",
        }
    )

    assert result == OrderResult(order_id="9002", status="Error:321", accepted=False)


def test_ibkr_paper_ibapi_runtime_app_returns_sanitized_order_error_message() -> None:
    app = _IBKRPaperSandboxIBAPIApp()
    app._connect = lambda **kwargs: None
    app._build_contract = lambda payload: object()
    app._build_order = lambda payload: object()
    app._app.next_order_id = 77

    def reject_order(order_id: int, contract: object, order: object) -> None:
        app._app.error(
            order_id,
            321,
            "Error validating request for DU123456 with token SECRET_VALUE",
        )

    app._app.placeOrder = reject_order

    result = app.place_order(
        host="127.0.0.1",
        port=4002,
        client_id=101,
        timeout_seconds=Decimal("1.0000"),
        payload={"symbol": "AAPL", "side": "BUY", "quantity": "1", "price": "0.01"},
    )

    assert result == {
        "order_id": "77",
        "status": "Error:321",
        "accepted": "false",
        "message": "Error validating request for DU[redacted] with token [redacted]",
    }


def test_ibkr_paper_ibapi_runtime_app_treats_status_timeout_as_rejection() -> None:
    app = _IBKRPaperSandboxIBAPIApp()
    app._connect = lambda **kwargs: None
    app._build_contract = lambda payload: object()
    app._build_order = lambda payload: object()
    app._app.next_order_id = 78
    app._app.placeOrder = lambda order_id, contract, order: None

    result = app.place_order(
        host="127.0.0.1",
        port=4002,
        client_id=101,
        timeout_seconds=Decimal("0.0001"),
        payload={"symbol": "AAPL", "side": "BUY", "quantity": "1", "price": "0.01"},
    )

    assert result == {
        "order_id": "78",
        "status": "StatusTimeout",
        "accepted": "false",
    }


def test_ibkr_paper_ibapi_runtime_order_disables_unsupported_legacy_flags() -> None:
    app = _IBKRPaperSandboxIBAPIApp()

    order = app._build_order(
        {
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": "1.00000000",
            "price": "0.01000000",
            "order_type": "limit",
        }
    )

    assert order.eTradeOnly is False
    assert order.firmQuoteOnly is False


def test_ibkr_paper_ibapi_runtime_cancel_succeeds_when_order_is_no_longer_open() -> None:
    app = _IBKRPaperSandboxIBAPIApp()
    app._connect = lambda **kwargs: None
    app._app.cancelOrder = lambda order_id, *args: None
    app._app.reqOpenOrders = lambda: app._app.openOrderEnd()

    cancelled = app.cancel_order(
        host="127.0.0.1",
        port=4002,
        client_id=101,
        timeout_seconds=Decimal("0.0001"),
        order_id="79",
    )

    assert cancelled is True


def test_ibkr_paper_sandbox_adapter_rejects_when_env_credentials_missing() -> None:
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ={})

    result = broker.place_order_if_allowed(
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approved_request(),
    )

    assert broker.is_available is False
    assert result.accepted is False
    assert result.message == "broker_credentials_missing"
    assert client.orders == []


def test_ibkr_paper_sandbox_health_check_is_unavailable_when_env_credentials_missing() -> None:
    checked_at = datetime(2026, 5, 1, 1, 0, tzinfo=UTC)
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ={})

    report = broker.check_connection(checked_at=checked_at)

    assert report.available is False
    assert report.healthy is False
    assert report.status == "unavailable"
    assert report.message == "broker_credentials_missing"
    assert report.checked_at == checked_at
    assert report.checks == {
        "broker_name": "ibkr",
        "mode": "paper",
        "credentials_configured": False,
        "client_configured": True,
    }
    assert client.health_checks == []


def test_ibkr_paper_sandbox_health_check_rejects_non_paper_mode_without_client_call() -> None:
    checked_at = datetime(2026, 5, 1, 1, 5, tzinfo=UTC)
    env = {**_ibkr_env(), "IBKR_PAPER_SANDBOX_MODE": "live"}
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=env)

    report = broker.check_connection(checked_at=checked_at)

    assert report.available is False
    assert report.healthy is False
    assert report.status == "unavailable"
    assert report.message == "paper_sandbox_mode_required"
    assert report.checked_at == checked_at
    assert client.health_checks == []


def test_ibkr_paper_sandbox_health_check_skips_connection_without_client() -> None:
    checked_at = datetime(2026, 5, 1, 1, 10, tzinfo=UTC)
    broker = IBKRPaperSandboxBroker(client=None, environ=_ibkr_env())

    report = broker.check_connection(checked_at=checked_at)

    assert report.available is False
    assert report.healthy is False
    assert report.status == "unavailable"
    assert report.message == "broker_client_missing"
    assert report.checks["credentials_configured"] is True
    assert report.checks["client_configured"] is False


def test_ibkr_paper_sandbox_health_check_reports_healthy_with_utc_timestamp() -> None:
    checked_at = datetime(2026, 5, 1, 1, 15, tzinfo=UTC)
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    report = broker.check_connection(checked_at=checked_at)

    assert report.available is True
    assert report.healthy is True
    assert report.status == "healthy"
    assert report.message is None
    assert report.checked_at == checked_at
    assert report.checked_at.tzinfo is UTC
    assert report.checks == {
        "broker_name": "ibkr",
        "mode": "paper",
        "credentials_configured": True,
        "client_configured": True,
        "server_time": "2026-05-01T00:00:00+00:00",
        "server_version": "paper-sandbox",
    }
    assert client.health_checks == [
        {
            "host": "127.0.0.1",
            "port": "7497",
            "client_id": "101",
            "mode": "paper",
        }
    ]


def test_ibkr_paper_sandbox_health_check_redacts_client_errors() -> None:
    checked_at = datetime(2026, 5, 1, 1, 20, tzinfo=UTC)
    client = FailingIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    report = broker.check_connection(checked_at=checked_at)

    assert report.available is True
    assert report.healthy is False
    assert report.status == "unhealthy"
    assert report.message == "ibkr_paper_sandbox_connection_failed"
    assert "DU123456" not in str(report.checks)
    assert "SECRET" not in str(report.checks)
    assert report.checks["error_type"] == "RuntimeError"


def test_ibkr_paper_sandbox_health_check_rejects_naive_checked_at() -> None:
    broker = IBKRPaperSandboxBroker(client=FakeIBKRClient(), environ=_ibkr_env())

    try:
        broker.check_connection(checked_at=datetime(2026, 5, 1, 1, 25))
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive IBKR paper sandbox health-check timestamps must be rejected")


def test_ibkr_paper_account_snapshot_is_unavailable_when_env_credentials_missing() -> None:
    as_of = datetime(2026, 5, 1, 2, 0, tzinfo=UTC)
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ={})

    snapshot = broker.get_account_snapshot(as_of=as_of)

    assert snapshot.available is False
    assert snapshot.healthy is False
    assert snapshot.status == "unavailable"
    assert snapshot.message == "broker_credentials_missing"
    assert snapshot.as_of == as_of
    assert client.health_checks == []
    assert client.account_snapshots == []


def test_ibkr_paper_account_snapshot_rejects_non_paper_mode_without_client_call() -> None:
    as_of = datetime(2026, 5, 1, 2, 5, tzinfo=UTC)
    env = {**_ibkr_env(), "IBKR_PAPER_SANDBOX_MODE": "live"}
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=env)

    snapshot = broker.get_account_snapshot(as_of=as_of)

    assert snapshot.available is False
    assert snapshot.healthy is False
    assert snapshot.status == "unavailable"
    assert snapshot.message == "paper_sandbox_mode_required"
    assert client.health_checks == []
    assert client.account_snapshots == []


def test_ibkr_paper_account_snapshot_requires_healthy_connection() -> None:
    as_of = datetime(2026, 5, 1, 2, 10, tzinfo=UTC)
    client = FailingIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    snapshot = broker.get_account_snapshot(as_of=as_of)

    assert snapshot.available is True
    assert snapshot.healthy is False
    assert snapshot.status == "unhealthy"
    assert snapshot.message == "ibkr_paper_sandbox_connection_failed"
    assert client.health_checks != []
    assert client.account_snapshots == []


def test_ibkr_paper_account_snapshot_returns_decimal_safe_read_only_values() -> None:
    as_of = datetime(2026, 5, 1, 2, 15, tzinfo=UTC)
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    snapshot = broker.get_account_snapshot(as_of=as_of)

    assert snapshot.available is True
    assert snapshot.healthy is True
    assert snapshot.status == "healthy"
    assert snapshot.message is None
    assert snapshot.as_of == as_of
    assert snapshot.net_liquidation == Decimal("100000.12345678")
    assert snapshot.cash == Decimal("25000.00000000")
    assert snapshot.buying_power == Decimal("50000.00000000")
    assert snapshot.unrealized_pnl == Decimal("-12.34000000")
    assert snapshot.realized_pnl == Decimal("100.01000000")
    assert snapshot.currency == "USD"
    assert client.account_snapshots == [
        {
            "host": "127.0.0.1",
            "port": "7497",
            "client_id": "101",
            "mode": "paper",
        }
    ]
    assert "DU123456" not in str(snapshot.diagnostics)


def test_ibkr_paper_account_snapshot_redacts_client_errors() -> None:
    as_of = datetime(2026, 5, 1, 2, 20, tzinfo=UTC)
    client = FailingAccountIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    snapshot = broker.get_account_snapshot(as_of=as_of)

    assert snapshot.available is True
    assert snapshot.healthy is False
    assert snapshot.status == "unhealthy"
    assert snapshot.message == "ibkr_paper_account_snapshot_failed"
    assert "DU123456" not in str(snapshot.diagnostics)
    assert "SECRET" not in str(snapshot.diagnostics)
    assert snapshot.diagnostics["error_type"] == "RuntimeError"


def test_ibkr_paper_account_snapshot_rejects_naive_as_of() -> None:
    broker = IBKRPaperSandboxBroker(client=FakeIBKRClient(), environ=_ibkr_env())

    try:
        broker.get_account_snapshot(as_of=datetime(2026, 5, 1, 2, 25))
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive IBKR paper account snapshot timestamps must be rejected")


def test_ibkr_paper_order_lifecycle_dry_run_rejects_when_readiness_fails() -> None:
    submitted_at = datetime(2026, 5, 1, 3, 0, tzinfo=UTC)
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.dry_run_order_lifecycle(
        config=_live_config(daily_notional_limit="100.00000000"),
        order_request=_order_request(),
        routing_request=_approved_request(),
        submitted_at=submitted_at,
    )

    assert result.accepted is False
    assert result.status == "rejected"
    assert result.reject_reason == "daily_notional_limit_exceeded"
    assert result.submitted_at == submitted_at
    assert result.lifecycle == ["rejected"]
    assert client.health_checks == []
    assert client.account_snapshots == []
    assert client.orders == []


def test_ibkr_paper_order_lifecycle_dry_run_rejects_when_routing_guard_fails() -> None:
    submitted_at = datetime(2026, 5, 1, 3, 5, tzinfo=UTC)
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.dry_run_order_lifecycle(
        config=_live_config(routing_enabled=False),
        order_request=_order_request(),
        routing_request=_approved_request(),
        submitted_at=submitted_at,
    )

    assert result.accepted is False
    assert result.status == "rejected"
    assert result.reject_reason == "real_broker_routing_disabled"
    assert result.lifecycle == ["rejected"]
    assert client.health_checks == []
    assert client.account_snapshots == []
    assert client.orders == []


def test_ibkr_paper_order_lifecycle_dry_run_rejects_without_manual_approval() -> None:
    submitted_at = datetime(2026, 5, 1, 3, 10, tzinfo=UTC)
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())
    missing_approval = LiveBrokerRoutingRequest(
        broker_name="ibkr",
        credentials_configured=True,
        manual_approval_id=None,
        approval_actor=None,
        approved_at=None,
    )

    result = broker.dry_run_order_lifecycle(
        config=_live_config(),
        order_request=_order_request(),
        routing_request=missing_approval,
        submitted_at=submitted_at,
    )

    assert result.accepted is False
    assert result.status == "rejected"
    assert result.reject_reason == "manual_approval_missing"
    assert result.lifecycle == ["rejected"]
    assert client.health_checks == []
    assert client.account_snapshots == []
    assert client.orders == []


def test_ibkr_paper_order_lifecycle_dry_run_requires_healthy_connection_and_account() -> None:
    submitted_at = datetime(2026, 5, 1, 3, 15, tzinfo=UTC)
    client = FailingIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.dry_run_order_lifecycle(
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approved_request(),
        submitted_at=submitted_at,
    )

    assert result.accepted is False
    assert result.status == "rejected"
    assert result.reject_reason == "ibkr_paper_sandbox_connection_failed"
    assert result.lifecycle == ["rejected"]
    assert client.health_checks != []
    assert client.account_snapshots == []
    assert client.orders == []


def test_ibkr_paper_order_lifecycle_dry_run_maps_submitted_and_accepted_without_order_call() -> None:
    submitted_at = datetime(2026, 5, 1, 3, 20, tzinfo=UTC)
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.dry_run_order_lifecycle(
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approved_request(),
        submitted_at=submitted_at,
    )

    assert result.accepted is True
    assert result.status == "accepted"
    assert result.reject_reason is None
    assert result.lifecycle == ["submitted", "accepted"]
    assert result.order_notional == Decimal("230.00000000")
    assert result.symbol == "XAUUSD"
    assert result.side == "BUY"
    assert result.quantity == Decimal("0.10000000")
    assert result.price == Decimal("2300.00000000")
    assert result.submitted_at == submitted_at
    assert result.cancel_requested_at is None
    assert result.diagnostics["manual_approval_id"] == "approval-ibkr-paper-1"
    assert client.account_snapshots != []
    assert client.orders == []


def test_ibkr_paper_order_lifecycle_dry_run_maps_cancel_preview_without_order_call() -> None:
    submitted_at = datetime(2026, 5, 1, 3, 25, tzinfo=UTC)
    cancel_requested_at = datetime(2026, 5, 1, 3, 26, tzinfo=UTC)
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.dry_run_order_lifecycle(
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approved_request(),
        submitted_at=submitted_at,
        cancel_requested_at=cancel_requested_at,
    )

    assert result.accepted is True
    assert result.status == "cancelled"
    assert result.lifecycle == ["submitted", "accepted", "cancel_requested", "cancelled"]
    assert result.cancel_requested_at == cancel_requested_at
    assert client.orders == []


def test_ibkr_paper_order_lifecycle_dry_run_rejects_naive_timestamps() -> None:
    broker = IBKRPaperSandboxBroker(client=FakeIBKRClient(), environ=_ibkr_env())

    try:
        broker.dry_run_order_lifecycle(
            config=_live_config(),
            order_request=_order_request(),
            routing_request=_approved_request(),
            submitted_at=datetime(2026, 5, 1, 3, 30),
        )
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive IBKR paper dry-run submitted_at timestamps must be rejected")


def test_ibkr_paper_sandbox_adapter_skips_client_when_routing_disabled() -> None:
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.place_order_if_allowed(
        config=_live_config(routing_enabled=False),
        order_request=_order_request(),
        routing_request=_approved_request(),
    )

    assert result.accepted is False
    assert result.message == "real_broker_routing_disabled"
    assert client.orders == []


def test_ibkr_paper_sandbox_adapter_skips_client_without_manual_approval() -> None:
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())
    missing_approval = LiveBrokerRoutingRequest(
        broker_name="ibkr",
        credentials_configured=True,
        manual_approval_id=None,
        approval_actor=None,
        approved_at=None,
    )

    result = broker.place_order_if_allowed(
        config=_live_config(),
        order_request=_order_request(),
        routing_request=missing_approval,
    )

    assert result.accepted is False
    assert result.message == "manual_approval_missing"
    assert client.orders == []


def test_ibkr_paper_sandbox_adapter_skips_client_when_readiness_fails() -> None:
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.place_order_if_allowed(
        config=_live_config(daily_notional_limit="100.00000000"),
        order_request=_order_request(),
        routing_request=_approved_request(),
    )

    assert result.accepted is False
    assert result.message == "daily_notional_limit_exceeded"
    assert client.orders == []


def test_ibkr_paper_sandbox_adapter_calls_client_only_after_all_guards_pass() -> None:
    client = FakeIBKRClient()
    broker = IBKRPaperSandboxBroker(client=client, environ=_ibkr_env())

    result = broker.place_order_if_allowed(
        config=_live_config(),
        order_request=_order_request(),
        routing_request=_approved_request(),
        stop_loss=Decimal("2290.00000000"),
        take_profit=Decimal("2320.00000000"),
    )

    assert result.accepted is True
    assert result.order_id == "ibkr-paper-1"
    assert client.orders == [
        {
            "account_id": "DU123456",
            "symbol": "XAUUSD",
            "side": "BUY",
            "quantity": "0.10000000",
            "price": "2300.00000000",
            "order_type": "market",
            "stop_loss": "2290.00000000",
            "take_profit": "2320.00000000",
            "manual_approval_id": "approval-ibkr-paper-1",
            "approval_actor": "phase5_admin",
            "approved_at": "2026-04-30T08:30:00+00:00",
        }
    ]
