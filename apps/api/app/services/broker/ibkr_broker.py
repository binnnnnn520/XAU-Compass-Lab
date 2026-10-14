from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from threading import Event, Thread
from time import sleep
from typing import Any, Mapping, Protocol

from app.services.broker.interface import AccountData, BrokerInterface, OrderResult, PositionData
from app.services.live_readiness import (
    LiveBrokerRoutingRequest,
    LiveOrderRequest,
    LiveReadinessConfig,
    evaluate_live_broker_routing,
    evaluate_live_order_readiness,
)

MONEY_QUANTIZER = Decimal("0.00000001")
IBKR_ACCEPTED_ORDER_STATUSES = {"ApiPending", "PendingSubmit", "PreSubmitted", "Submitted", "Filled"}


@dataclass(frozen=True)
class IBKRPaperSandboxCredentials:
    host: str
    port: int
    client_id: int
    account_id: str
    mode: str = "paper"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> IBKRPaperSandboxCredentials | None:
        env = os.environ if environ is None else environ
        mode = env.get("IBKR_PAPER_SANDBOX_MODE", "").strip().lower()
        host = env.get("IBKR_PAPER_SANDBOX_HOST", "").strip()
        port = env.get("IBKR_PAPER_SANDBOX_PORT", "").strip()
        client_id = env.get("IBKR_PAPER_SANDBOX_CLIENT_ID", "").strip()
        account_id = env.get("IBKR_PAPER_SANDBOX_ACCOUNT_ID", "").strip()

        if mode != "paper" or not host or not port or not client_id or not account_id:
            return None

        try:
            parsed_port = int(port)
            parsed_client_id = int(client_id)
        except ValueError:
            return None

        return cls(
            host=host,
            port=parsed_port,
            client_id=parsed_client_id,
            account_id=account_id,
            mode=mode,
        )


@dataclass(frozen=True)
class IBKRPaperSandboxHealthReport:
    available: bool
    healthy: bool
    checked_at: datetime
    status: str
    message: str | None
    checks: dict[str, object]


@dataclass(frozen=True)
class IBKRPaperSandboxAccountSnapshot:
    available: bool
    healthy: bool
    as_of: datetime
    status: str
    message: str | None
    net_liquidation: Decimal | None = None
    cash: Decimal | None = None
    buying_power: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    realized_pnl: Decimal | None = None
    currency: str | None = None
    diagnostics: dict[str, object] | None = None


@dataclass(frozen=True)
class IBKRPaperSandboxOrderLifecycleDryRun:
    accepted: bool
    status: str
    reject_reason: str | None
    lifecycle: list[str]
    submitted_at: datetime
    cancel_requested_at: datetime | None
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    order_notional: Decimal
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class IBKRPaperSandboxOrderExecutionResult:
    accepted: bool
    status: str
    reject_reason: str | None
    lifecycle: list[str]
    submitted_at: datetime
    cancel_requested_at: datetime | None
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    order_notional: Decimal
    submitted_order_id: str | None
    close_order_id: str | None
    cancelled: bool
    diagnostics: dict[str, object]


class IBKRPaperSandboxClient(Protocol):
    def place_order(self, payload: dict[str, str]) -> OrderResult:
        ...

    def check_connection(self, payload: dict[str, str]) -> dict[str, Any]:
        ...

    def get_account_snapshot(self, payload: dict[str, str]) -> dict[str, Any]:
        ...


class IBKRPaperSandboxIBAPIClient:
    def __init__(
        self,
        *,
        app_factory: Callable[[], Any] | None = None,
        credentials: IBKRPaperSandboxCredentials | None = None,
        expected_account_id: str | None = None,
        order_execution_enabled: bool = False,
        timeout_seconds: Decimal = Decimal("10.0000"),
        reconnect_cooldown_seconds: Decimal | None = None,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._app_factory = app_factory or _IBKRPaperSandboxIBAPIApp
        self._credentials = credentials
        self._expected_account_id = expected_account_id
        self._order_execution_enabled = order_execution_enabled
        self._timeout_seconds = Decimal(str(timeout_seconds))
        if reconnect_cooldown_seconds is None:
            reconnect_cooldown_seconds = Decimal("0.0000") if app_factory is not None else Decimal("2.0000")
        self._reconnect_cooldown_seconds = Decimal(str(reconnect_cooldown_seconds))
        self._sleeper = sleeper

    def place_order(self, payload: dict[str, str]) -> OrderResult:
        if not self._order_execution_enabled:
            raise NotImplementedError("IBKR paper ibapi order execution is disabled by default.")
        connection = self._connection_from_payload(payload)
        app = self._app_factory()
        try:
            raw_result = app.place_order(
                host=connection.host,
                port=connection.port,
                client_id=connection.client_id,
                timeout_seconds=self._timeout_seconds,
                payload=_contract_payload(payload),
            )
        finally:
            self._disconnect_app(app)
        return _order_result_from_client(raw_result)

    def cancel_order(self, order_id: str, payload: dict[str, str]) -> bool:
        if not self._order_execution_enabled:
            raise NotImplementedError("IBKR paper ibapi order execution is disabled by default.")
        connection = self._connection_from_payload(payload)
        app = self._app_factory()
        try:
            return bool(
                app.cancel_order(
                    host=connection.host,
                    port=connection.port,
                    client_id=connection.client_id,
                    timeout_seconds=self._timeout_seconds,
                    order_id=order_id,
                )
            )
        finally:
            self._disconnect_app(app)

    def check_connection(self, payload: dict[str, str]) -> dict[str, str]:
        app = self._app_factory()
        try:
            report = app.connect_and_check(
                host=_payload_str(payload, "host"),
                port=_payload_int(payload, "port"),
                client_id=_payload_int(payload, "client_id"),
                timeout_seconds=self._timeout_seconds,
            )
        finally:
            self._disconnect_app(app)

        return {
            "server_time": str(report["server_time"]),
            "server_version": str(report["server_version"]),
        }

    def get_account_snapshot(self, payload: dict[str, str]) -> dict[str, str]:
        app = self._app_factory()
        try:
            raw_snapshot = app.get_account_summary(
                host=_payload_str(payload, "host"),
                port=_payload_int(payload, "port"),
                client_id=_payload_int(payload, "client_id"),
                timeout_seconds=self._timeout_seconds,
            )
        finally:
            self._disconnect_app(app)

        account_id = str(raw_snapshot.get("account_id", ""))
        if self._expected_account_id is not None and account_id != self._expected_account_id:
            raise RuntimeError("ibkr_paper_account_mismatch")

        return {
            "net_liquidation": _snapshot_decimal_payload(raw_snapshot, "net_liquidation"),
            "cash": _snapshot_decimal_payload(raw_snapshot, "cash"),
            "buying_power": _snapshot_decimal_payload(raw_snapshot, "buying_power"),
            "unrealized_pnl": _snapshot_decimal_payload(
                raw_snapshot,
                "unrealized_pnl",
                default=Decimal("0.00000000"),
            ),
            "realized_pnl": _snapshot_decimal_payload(
                raw_snapshot,
                "realized_pnl",
                default=Decimal("0.00000000"),
            ),
            "currency": str(raw_snapshot.get("currency", "")),
        }

    def get_positions(self, payload: dict[str, str]) -> list[dict[str, str]]:
        connection = self._credentials or IBKRPaperSandboxCredentials(
            host=_payload_str(payload, "host"),
            port=_payload_int(payload, "port"),
            client_id=_payload_int(payload, "client_id"),
            account_id=str(payload.get("account_id", self._expected_account_id or "")),
            mode="paper",
        )
        app = self._app_factory()
        try:
            raw_positions = app.get_positions(
                host=connection.host,
                port=connection.port,
                client_id=connection.client_id,
                timeout_seconds=self._timeout_seconds,
            )
        finally:
            self._disconnect_app(app)

        sanitized_positions: list[dict[str, str]] = []
        for position in raw_positions:
            account_id = str(position.get("account_id", ""))
            if self._expected_account_id is not None and account_id != self._expected_account_id:
                raise RuntimeError("ibkr_paper_account_mismatch")
            sanitized_positions.append(
                {
                    "symbol": str(position.get("symbol", "")),
                    "quantity": _snapshot_decimal_payload(position, "quantity", default=Decimal("0.00000000")),
                    "entry_price": _snapshot_decimal_payload(position, "entry_price", default=Decimal("0.00000000")),
                    "status": str(position.get("status", "open")),
                }
            )
        return sanitized_positions

    def _connection_from_payload(self, payload: Mapping[str, str]) -> IBKRPaperSandboxCredentials:
        if self._credentials is not None:
            return self._credentials
        return IBKRPaperSandboxCredentials(
            host=_payload_str(payload, "host"),
            port=_payload_int(payload, "port"),
            client_id=_payload_int(payload, "client_id"),
            account_id=_payload_str(payload, "account_id"),
            mode="paper",
        )

    def _disconnect_app(self, app: Any) -> None:
        app.disconnect()
        if self._reconnect_cooldown_seconds > 0:
            self._sleeper(float(self._reconnect_cooldown_seconds))


class _IBKRPaperSandboxIBAPIApp:
    _ACCOUNT_SUMMARY_TAGS = (
        "NetLiquidation,TotalCashValue,BuyingPower,UnrealizedPnL,RealizedPnL"
    )
    _ACCOUNT_FIELD_MAP = {
        "NetLiquidation": "net_liquidation",
        "TotalCashValue": "cash",
        "BuyingPower": "buying_power",
        "UnrealizedPnL": "unrealized_pnl",
        "RealizedPnL": "realized_pnl",
    }

    def __init__(self) -> None:
        try:
            from ibapi.client import EClient
            from ibapi.wrapper import EWrapper
        except ModuleNotFoundError as exc:
            raise RuntimeError("ibapi_dependency_missing") from exc

        class RuntimeApp(EWrapper, EClient):  # type: ignore[misc, valid-type]
            def __init__(self) -> None:
                EClient.__init__(self, self)
                self.connected_event = Event()
                self.current_time_event = Event()
                self.account_summary_event = Event()
                self.order_status_event = Event()
                self.open_orders_event = Event()
                self.server_time: datetime | None = None
                self.next_order_id: int | None = None
                self.account_summaries: dict[str, dict[str, str]] = {}
                self.order_statuses: dict[int, str] = {}
                self.order_error_messages: dict[int, str] = {}
                self.open_order_ids: set[int] = set()
                self.positions: list[dict[str, str]] = []
                self.positions_event = Event()
                self.errors: list[dict[str, str]] = []

            def nextValidId(self, orderId: int) -> None:
                self.next_order_id = orderId
                self.connected_event.set()

            def currentTime(self, time: int) -> None:
                self.server_time = datetime.fromtimestamp(time, UTC)
                self.current_time_event.set()

            def accountSummary(
                self,
                reqId: int,
                account: str,
                tag: str,
                value: str,
                currency: str,
            ) -> None:
                account_summary = self.account_summaries.setdefault(
                    account,
                    {"account_id": account, "currency": currency},
                )
                field_name = _IBKRPaperSandboxIBAPIApp._ACCOUNT_FIELD_MAP.get(tag)
                if field_name is not None:
                    account_summary[field_name] = value
                    if currency:
                        account_summary["currency"] = currency

            def accountSummaryEnd(self, reqId: int) -> None:
                self.account_summary_event.set()

            def orderStatus(
                self,
                orderId: int,
                status: str,
                filled: float,
                remaining: float,
                avgFillPrice: float,
                permId: int,
                parentId: int,
                lastFillPrice: float,
                clientId: int,
                whyHeld: str,
                *args: object,
            ) -> None:
                self.order_statuses[orderId] = status
                self.order_status_event.set()

            def openOrder(self, orderId: int, contract: Any, order: Any, orderState: Any) -> None:
                self.open_order_ids.add(orderId)

            def openOrderEnd(self) -> None:
                self.open_orders_event.set()

            def position(self, account: str, contract: Any, position: float, avgCost: float) -> None:
                if position == 0:
                    return
                self.positions.append(
                    {
                        "account_id": str(account),
                        "symbol": str(getattr(contract, "symbol", "")),
                        "quantity": str(position),
                        "entry_price": str(avgCost),
                        "status": "open",
                    }
                )

            def positionEnd(self) -> None:
                self.positions_event.set()

            def error(
                self,
                reqId: int,
                errorCode: int,
                errorString: str,
                *args: object,
            ) -> None:
                self.errors.append(
                    {
                        "req_id": str(reqId),
                        "error_code": str(errorCode),
                    }
                )
                if reqId > 0:
                    self.order_statuses[reqId] = f"Error:{errorCode}"
                    self.order_error_messages[reqId] = _sanitize_ibkr_error_message(errorString)
                    self.order_status_event.set()

        self._app = RuntimeApp()
        self._thread: Thread | None = None

    def connect_and_check(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
    ) -> dict[str, str]:
        self._connect(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=timeout_seconds,
        )
        self._app.reqCurrentTime()
        if not self._app.current_time_event.wait(float(timeout_seconds)):
            raise TimeoutError("ibkr_paper_current_time_timeout")
        if self._app.server_time is None:
            raise RuntimeError("ibkr_paper_current_time_missing")
        return {
            "server_time": self._app.server_time.isoformat(),
            "server_version": str(self._app.serverVersion()),
        }

    def get_account_summary(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
    ) -> dict[str, str]:
        self._connect(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=timeout_seconds,
        )
        request_id = 9001
        self._app.reqAccountSummary(request_id, "All", self._ACCOUNT_SUMMARY_TAGS)
        if not self._app.account_summary_event.wait(float(timeout_seconds)):
            raise TimeoutError("ibkr_paper_account_summary_timeout")
        try:
            self._app.cancelAccountSummary(request_id)
        except Exception:
            pass
        if not self._app.account_summaries:
            raise RuntimeError("ibkr_paper_account_summary_empty")

        account_summary = next(iter(self._app.account_summaries.values()))
        required_fields = {
            "account_id",
            "net_liquidation",
            "cash",
            "buying_power",
            "currency",
        }
        if not required_fields.issubset(account_summary):
            raise RuntimeError("ibkr_paper_account_summary_incomplete")
        account_summary.setdefault("unrealized_pnl", "0.00000000")
        account_summary.setdefault("realized_pnl", "0.00000000")
        return account_summary

    def get_positions(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
    ) -> list[dict[str, str]]:
        self._connect(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=timeout_seconds,
        )
        self._app.positions_event.clear()
        self._app.positions.clear()
        self._app.reqPositions()
        if not self._app.positions_event.wait(float(timeout_seconds)):
            raise TimeoutError("ibkr_paper_positions_timeout")
        try:
            self._app.cancelPositions()
        except Exception:
            pass
        return list(self._app.positions)

    def place_order(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
        payload: dict[str, str],
    ) -> dict[str, str]:
        self._connect(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=timeout_seconds,
        )
        order_id = self._app.next_order_id
        if order_id is None:
            raise RuntimeError("ibkr_paper_next_order_id_missing")
        contract = self._build_contract(payload)
        order = self._build_order(payload)
        self._app.order_status_event.clear()
        self._app.order_statuses.pop(order_id, None)
        self._app.placeOrder(order_id, contract, order)
        status = self._wait_order_status(order_id, timeout_seconds)
        accepted = status in IBKR_ACCEPTED_ORDER_STATUSES
        result = {
            "order_id": str(order_id),
            "status": status,
            "accepted": "true" if accepted else "false",
        }
        if status.startswith("Error:") and order_id in self._app.order_error_messages:
            result["message"] = self._app.order_error_messages[order_id]
        return result

    def cancel_order(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
        order_id: str,
    ) -> bool:
        self._connect(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=timeout_seconds,
        )
        numeric_order_id = int(order_id)
        self._app.order_status_event.clear()
        self._app.order_statuses.pop(numeric_order_id, None)
        try:
            from ibapi.order_cancel import OrderCancel

            self._app.cancelOrder(numeric_order_id, OrderCancel())
        except (ModuleNotFoundError, TypeError):
            self._app.cancelOrder(numeric_order_id)
        status = self._wait_order_status(numeric_order_id, timeout_seconds)
        if status in {"Cancelled", "ApiCancelled", "PendingCancel"}:
            return True
        return not self._order_remains_open(numeric_order_id, timeout_seconds)

    def disconnect(self) -> None:
        try:
            self._app.disconnect()
        finally:
            if self._thread is not None:
                self._thread.join(timeout=1)
                self._thread = None

    def _connect(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout_seconds: Decimal,
    ) -> None:
        connected = self._app.connect(host, port, client_id)
        if connected is False:
            raise RuntimeError("ibkr_paper_connect_failed")
        self._thread = Thread(target=self._app.run, daemon=True)
        self._thread.start()
        if not self._app.connected_event.wait(float(timeout_seconds)):
            raise TimeoutError("ibkr_paper_connection_timeout")

    def _wait_order_status(self, order_id: int, timeout_seconds: Decimal) -> str:
        if not self._app.order_status_event.wait(float(timeout_seconds)):
            return "StatusTimeout"
        return str(self._app.order_statuses.get(order_id, "Unknown"))

    def _order_remains_open(self, order_id: int, timeout_seconds: Decimal) -> bool:
        self._app.open_orders_event.clear()
        self._app.open_order_ids.clear()
        self._app.reqOpenOrders()
        if not self._app.open_orders_event.wait(float(timeout_seconds)):
            return True
        return order_id in self._app.open_order_ids

    def _build_contract(self, payload: Mapping[str, str]) -> Any:
        from ibapi.contract import Contract

        contract = Contract()
        if payload.get("con_id"):
            contract.conId = int(str(payload["con_id"]))
        contract.symbol = str(payload.get("symbol", ""))
        contract.secType = str(payload.get("sec_type", ""))
        contract.exchange = str(payload.get("exchange", ""))
        contract.currency = str(payload.get("currency", ""))
        if payload.get("primary_exchange"):
            contract.primaryExchange = str(payload["primary_exchange"])
        if payload.get("local_symbol"):
            contract.localSymbol = str(payload["local_symbol"])
        return contract

    def _build_order(self, payload: Mapping[str, str]) -> Any:
        from ibapi.order import Order

        order = Order()
        order.action = str(payload.get("side", "")).upper()
        order.totalQuantity = float(Decimal(str(payload.get("quantity", "0"))))
        order_type = str(payload.get("order_type", "limit")).lower()
        order.orderType = "MKT" if order_type == "market" else "LMT"
        if order.orderType == "LMT":
            order.lmtPrice = float(Decimal(str(payload.get("price", "0"))))
        order.account = str(payload.get("account_id", ""))
        order.tif = "DAY"
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        order.transmit = True
        return order


def _decimal_payload(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(Decimal(str(value)), "f")


def _quantize_money(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("IBKR paper sandbox health-check datetimes must be UTC-aware")
    return value.astimezone(UTC)


def _credential_reject_reason(environ: Mapping[str, str]) -> str:
    mode = environ.get("IBKR_PAPER_SANDBOX_MODE", "").strip().lower()
    if mode and mode != "paper":
        return "paper_sandbox_mode_required"
    return "broker_credentials_missing"


def _decimal_from_snapshot(payload: Mapping[str, Any], key: str) -> Decimal:
    return Decimal(str(payload[key]))


def _snapshot_decimal_payload(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: Decimal | None = None,
) -> str:
    value = payload.get(key, default)
    if value is None:
        raise KeyError(key)
    return format(Decimal(str(value)), "f")


def _payload_str(payload: Mapping[str, str], key: str) -> str:
    return str(payload[key])


def _payload_int(payload: Mapping[str, str], key: str) -> int:
    return int(str(payload[key]))


def _order_result_from_client(value: Any) -> OrderResult:
    if isinstance(value, OrderResult):
        return value
    if isinstance(value, Mapping):
        return OrderResult(
            order_id=str(value.get("order_id", "")),
            status=str(value.get("status", "")),
            accepted=_bool_from_client(value.get("accepted", False)),
            message=None if value.get("message") is None else str(value.get("message")),
        )
    raise TypeError("ibkr paper client returned an unsupported order result")


def _bool_from_client(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "accepted"}:
            return True
        if normalized in {"", "0", "false", "no", "n", "rejected"}:
            return False
    return bool(value)


def _sanitize_ibkr_error_message(value: object) -> str:
    text = str(value)
    text = re.sub(r"\bDU\d+\b", "DU[redacted]", text)
    text = re.sub(
        r"(?i)\b(token|password|secret)\s+[^,\s;]+",
        lambda match: f"{match.group(1)} [redacted]",
        text,
    )
    return text[:240]


def _contract_payload(payload: Mapping[str, str]) -> dict[str, str]:
    allowed_keys = {
        "account_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "order_type",
        "sec_type",
        "exchange",
        "currency",
        "primary_exchange",
        "local_symbol",
        "con_id",
    }
    return {key: str(payload[key]) for key in allowed_keys if key in payload and str(payload[key])}


def _contract_payload_from_env(environ: Mapping[str, str]) -> dict[str, str]:
    env_map = {
        "IBKR_PAPER_ORDER_SEC_TYPE": "sec_type",
        "IBKR_PAPER_ORDER_EXCHANGE": "exchange",
        "IBKR_PAPER_ORDER_CURRENCY": "currency",
        "IBKR_PAPER_ORDER_PRIMARY_EXCHANGE": "primary_exchange",
        "IBKR_PAPER_ORDER_LOCAL_SYMBOL": "local_symbol",
        "IBKR_PAPER_ORDER_CON_ID": "con_id",
    }
    payload: dict[str, str] = {}
    for env_key, payload_key in env_map.items():
        value = environ.get(env_key, "").strip()
        if value:
            payload[payload_key] = value
    return payload


def _env_int(
    environ: Mapping[str, str],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(environ.get(key, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_decimal(
    environ: Mapping[str, str],
    key: str,
    *,
    default: Decimal,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    try:
        value = Decimal(str(environ.get(key, str(default))))
    except Exception:
        return default
    return max(minimum, min(maximum, value))


def _has_matching_open_position(positions: list[dict[str, str]], symbol: str) -> bool:
    return any(
        str(position.get("symbol", "")) == symbol
        and Decimal(str(position.get("quantity", "0"))) > Decimal("0")
        and str(position.get("status", "open")).lower() == "open"
        for position in positions
    )


def _opposite_side(side: str) -> str:
    return "SELL" if side.upper() == "BUY" else "BUY"


class IBKRBroker(BrokerInterface):
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
        raise NotImplementedError("IBKR live broker integration is blocked until Phase 5 readiness.")

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError("IBKR live broker integration is blocked until Phase 5 readiness.")

    def get_positions(self) -> list[PositionData]:
        raise NotImplementedError("IBKR live broker integration is blocked until Phase 5 readiness.")

    def get_account(self) -> AccountData:
        raise NotImplementedError("IBKR live broker integration is blocked until Phase 5 readiness.")


class IBKRPaperSandboxBroker(BrokerInterface):
    def __init__(
        self,
        *,
        client: IBKRPaperSandboxClient | None = None,
        credentials: IBKRPaperSandboxCredentials | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._client = client
        self._environ = os.environ if environ is None else environ
        self.credentials = (
            credentials if credentials is not None else IBKRPaperSandboxCredentials.from_env(self._environ)
        )
        self._credential_reject_reason = (
            None if self.credentials is not None else _credential_reject_reason(self._environ)
        )

    @property
    def is_available(self) -> bool:
        return self.credentials is not None and self._client is not None

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
        raise NotImplementedError("IBKR paper sandbox orders must use place_order_if_allowed(...).")

    def check_connection(self, *, checked_at: datetime | None = None) -> IBKRPaperSandboxHealthReport:
        checked_at_utc = _as_utc(checked_at)
        checks: dict[str, object] = {
            "broker_name": "ibkr",
            "mode": "paper",
            "credentials_configured": self.credentials is not None,
            "client_configured": self._client is not None,
        }

        if self.credentials is None:
            return IBKRPaperSandboxHealthReport(
                available=False,
                healthy=False,
                checked_at=checked_at_utc,
                status="unavailable",
                message=self._credential_reject_reason,
                checks=checks,
            )
        if self._client is None:
            return IBKRPaperSandboxHealthReport(
                available=False,
                healthy=False,
                checked_at=checked_at_utc,
                status="unavailable",
                message="broker_client_missing",
                checks=checks,
            )

        payload = {
            "host": self.credentials.host,
            "port": str(self.credentials.port),
            "client_id": str(self.credentials.client_id),
            "mode": self.credentials.mode,
        }
        try:
            client_report = self._client.check_connection(payload)
        except Exception as exc:
            return IBKRPaperSandboxHealthReport(
                available=True,
                healthy=False,
                checked_at=checked_at_utc,
                status="unhealthy",
                message="ibkr_paper_sandbox_connection_failed",
                checks={**checks, "error_type": type(exc).__name__},
            )

        safe_client_report = {
            str(key): str(value)
            for key, value in client_report.items()
            if str(key) in {"server_time", "server_version"}
        }
        return IBKRPaperSandboxHealthReport(
            available=True,
            healthy=True,
            checked_at=checked_at_utc,
            status="healthy",
            message=None,
            checks={**checks, **safe_client_report},
        )

    def get_account_snapshot(self, *, as_of: datetime | None = None) -> IBKRPaperSandboxAccountSnapshot:
        as_of_utc = _as_utc(as_of)
        health = self.check_connection(checked_at=as_of_utc)
        if not health.healthy:
            return IBKRPaperSandboxAccountSnapshot(
                available=health.available,
                healthy=False,
                as_of=as_of_utc,
                status=health.status,
                message=health.message,
                diagnostics=health.checks,
            )

        if self.credentials is None or self._client is None:
            return IBKRPaperSandboxAccountSnapshot(
                available=False,
                healthy=False,
                as_of=as_of_utc,
                status="unavailable",
                message="broker_client_missing",
                diagnostics=health.checks,
            )

        payload = {
            "host": self.credentials.host,
            "port": str(self.credentials.port),
            "client_id": str(self.credentials.client_id),
            "mode": self.credentials.mode,
        }
        try:
            client_snapshot = self._client.get_account_snapshot(payload)
        except Exception as exc:
            return IBKRPaperSandboxAccountSnapshot(
                available=True,
                healthy=False,
                as_of=as_of_utc,
                status="unhealthy",
                message="ibkr_paper_account_snapshot_failed",
                diagnostics={**health.checks, "error_type": type(exc).__name__},
            )

        return IBKRPaperSandboxAccountSnapshot(
            available=True,
            healthy=True,
            as_of=as_of_utc,
            status="healthy",
            message=None,
            net_liquidation=_decimal_from_snapshot(client_snapshot, "net_liquidation"),
            cash=_decimal_from_snapshot(client_snapshot, "cash"),
            buying_power=_decimal_from_snapshot(client_snapshot, "buying_power"),
            unrealized_pnl=_decimal_from_snapshot(client_snapshot, "unrealized_pnl"),
            realized_pnl=_decimal_from_snapshot(client_snapshot, "realized_pnl"),
            currency=str(client_snapshot.get("currency", "")) or None,
            diagnostics=health.checks,
        )

    def dry_run_order_lifecycle(
        self,
        *,
        config: LiveReadinessConfig,
        order_request: LiveOrderRequest,
        routing_request: LiveBrokerRoutingRequest,
        submitted_at: datetime,
        cancel_requested_at: datetime | None = None,
    ) -> IBKRPaperSandboxOrderLifecycleDryRun:
        submitted_at_utc = _as_utc(submitted_at)
        cancel_requested_at_utc = _as_utc(cancel_requested_at) if cancel_requested_at is not None else None
        order_notional = _quantize_money(order_request.quantity * order_request.price)

        readiness_decision = evaluate_live_order_readiness(config, order_request)
        if not readiness_decision.passed:
            return self._dry_run_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status="rejected",
                reject_reason=readiness_decision.reject_reason,
                lifecycle=["rejected"],
                diagnostics={
                    "dry_run": True,
                    "broker_name": "ibkr",
                    "mode": "paper",
                    "readiness_checks": readiness_decision.checks,
                },
            )

        guarded_routing_request = LiveBrokerRoutingRequest(
            broker_name="ibkr",
            credentials_configured=self.is_available,
            manual_approval_id=routing_request.manual_approval_id,
            approval_actor=routing_request.approval_actor,
            approved_at=routing_request.approved_at,
        )
        routing_decision = evaluate_live_broker_routing(
            config,
            readiness_decision,
            guarded_routing_request,
        )
        if not routing_decision.passed:
            return self._dry_run_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status="rejected",
                reject_reason=routing_decision.reject_reason,
                lifecycle=["rejected"],
                diagnostics={
                    "dry_run": True,
                    "broker_name": "ibkr",
                    "mode": "paper",
                    "routing_checks": routing_decision.checks,
                },
            )

        account_snapshot = self.get_account_snapshot(as_of=submitted_at_utc)
        if not account_snapshot.healthy:
            return self._dry_run_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status="rejected",
                reject_reason=account_snapshot.message or account_snapshot.status,
                lifecycle=["rejected"],
                diagnostics={
                    "dry_run": True,
                    "broker_name": "ibkr",
                    "mode": "paper",
                    "routing_checks": routing_decision.checks,
                    "account_snapshot_status": account_snapshot.status,
                    "account_snapshot_message": account_snapshot.message,
                },
            )

        lifecycle = ["submitted", "accepted"]
        status = "accepted"
        if cancel_requested_at_utc is not None:
            lifecycle = [*lifecycle, "cancel_requested", "cancelled"]
            status = "cancelled"

        return self._dry_run_result(
            order_request=order_request,
            submitted_at=submitted_at_utc,
            cancel_requested_at=cancel_requested_at_utc,
            order_notional=order_notional,
            accepted=True,
            status=status,
            reject_reason=None,
            lifecycle=lifecycle,
            diagnostics={
                "dry_run": True,
                "broker_name": "ibkr",
                "mode": "paper",
                "manual_approval_id": routing_decision.checks["manual_approval_id"],
                "approval_actor": routing_decision.checks["approval_actor"],
                "approved_at": routing_decision.checks["approved_at"],
                "account_snapshot_status": account_snapshot.status,
                "account_snapshot_as_of": account_snapshot.as_of.isoformat(),
            },
        )

    def execute_paper_order_lifecycle_if_allowed(
        self,
        *,
        execution_enabled: bool,
        config: LiveReadinessConfig,
        order_request: LiveOrderRequest,
        routing_request: LiveBrokerRoutingRequest,
        submitted_at: datetime,
        cancel_requested_at: datetime | None = None,
        close_existing_position: bool = False,
        order_type: str = "limit",
    ) -> IBKRPaperSandboxOrderExecutionResult:
        submitted_at_utc = _as_utc(submitted_at)
        cancel_requested_at_utc = _as_utc(cancel_requested_at) if cancel_requested_at is not None else None
        order_notional = _quantize_money(order_request.quantity * order_request.price)

        if not execution_enabled:
            return self._execution_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status="rejected",
                reject_reason="paper_order_execution_disabled",
                lifecycle=["rejected"],
                submitted_order_id=None,
                close_order_id=None,
                cancelled=False,
                diagnostics={"broker_name": "ibkr", "mode": "paper", "execution_enabled": False},
            )
        if self.credentials is None:
            return self._execution_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status="rejected",
                reject_reason=self._credential_reject_reason or "broker_credentials_missing",
                lifecycle=["rejected"],
                submitted_order_id=None,
                close_order_id=None,
                cancelled=False,
                diagnostics={"broker_name": "ibkr", "mode": "paper", "credentials_configured": False},
            )
        if self._client is None:
            return self._execution_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status="rejected",
                reject_reason="broker_client_missing",
                lifecycle=["rejected"],
                submitted_order_id=None,
                close_order_id=None,
                cancelled=False,
                diagnostics={"broker_name": "ibkr", "mode": "paper", "client_configured": False},
            )

        readiness_decision = evaluate_live_order_readiness(config, order_request)
        if not readiness_decision.passed:
            return self._execution_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status="rejected",
                reject_reason=readiness_decision.reject_reason,
                lifecycle=["rejected"],
                submitted_order_id=None,
                close_order_id=None,
                cancelled=False,
                diagnostics={"broker_name": "ibkr", "mode": "paper", "readiness_checks": readiness_decision.checks},
            )

        guarded_routing_request = LiveBrokerRoutingRequest(
            broker_name="ibkr",
            credentials_configured=self.is_available,
            manual_approval_id=routing_request.manual_approval_id,
            approval_actor=routing_request.approval_actor,
            approved_at=routing_request.approved_at,
        )
        routing_decision = evaluate_live_broker_routing(config, readiness_decision, guarded_routing_request)
        if not routing_decision.passed:
            return self._execution_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status="rejected",
                reject_reason=routing_decision.reject_reason,
                lifecycle=["rejected"],
                submitted_order_id=None,
                close_order_id=None,
                cancelled=False,
                diagnostics={"broker_name": "ibkr", "mode": "paper", "routing_checks": routing_decision.checks},
            )

        account_snapshot = self.get_account_snapshot(as_of=submitted_at_utc)
        if not account_snapshot.healthy:
            return self._execution_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status="rejected",
                reject_reason=account_snapshot.message or account_snapshot.status,
                lifecycle=["rejected"],
                submitted_order_id=None,
                close_order_id=None,
                cancelled=False,
                diagnostics={
                    "broker_name": "ibkr",
                    "mode": "paper",
                    "account_snapshot_status": account_snapshot.status,
                },
            )

        approval_payload = {
            "manual_approval_id": str(routing_decision.checks["manual_approval_id"]),
            "approval_actor": str(routing_decision.checks["approval_actor"]),
            "approved_at": str(routing_decision.checks["approved_at"]),
        }
        contract_payload = _contract_payload_from_env(self._environ)
        entry_result = _order_result_from_client(
            self._client.place_order(
                {
                    "account_id": self.credentials.account_id,
                    "symbol": order_request.symbol,
                    "side": order_request.side,
                    "quantity": _decimal_payload(order_request.quantity),
                    "price": _decimal_payload(order_request.price),
                    "order_type": order_type,
                    **contract_payload,
                    **approval_payload,
                    "order_role": "entry_verification",
                }
            )
        )
        if not entry_result.accepted:
            return self._execution_result(
                order_request=order_request,
                submitted_at=submitted_at_utc,
                cancel_requested_at=cancel_requested_at_utc,
                order_notional=order_notional,
                accepted=False,
                status=entry_result.status or "rejected",
                reject_reason=entry_result.message or "paper_order_rejected",
                lifecycle=["rejected"],
                submitted_order_id=entry_result.order_id or None,
                close_order_id=None,
                cancelled=False,
                diagnostics={"broker_name": "ibkr", "mode": "paper"},
            )

        lifecycle = ["submitted"]
        cancelled = False
        if cancel_requested_at_utc is not None:
            cancel_payload = {
                "account_id": self.credentials.account_id,
                "manual_approval_id": approval_payload["manual_approval_id"],
                "approval_actor": approval_payload["approval_actor"],
                "cancel_requested_at": cancel_requested_at_utc.isoformat(),
            }
            cancel_method = getattr(self._client, "cancel_order")
            cancelled = bool(cancel_method(entry_result.order_id, cancel_payload))
            lifecycle.extend(["cancel_requested", "cancelled" if cancelled else "cancel_failed"])

        close_order_id: str | None = None
        if close_existing_position:
            get_positions = getattr(self._client, "get_positions", None)
            matching_position_found = False
            if get_positions is not None:
                position_check_attempts = _env_int(
                    self._environ,
                    "IBKR_PAPER_POSITION_CONFIRMATION_ATTEMPTS",
                    default=3,
                    minimum=1,
                    maximum=10,
                )
                position_check_sleep_seconds = _env_decimal(
                    self._environ,
                    "IBKR_PAPER_POSITION_CONFIRMATION_SLEEP_SECONDS",
                    default=Decimal("1.0000"),
                    minimum=Decimal("0"),
                    maximum=Decimal("10.0000"),
                )
                for attempt_index in range(position_check_attempts):
                    positions = get_positions(
                        {"account_id": self.credentials.account_id, "symbol": order_request.symbol}
                    )
                    matching_position_found = _has_matching_open_position(positions, order_request.symbol)
                    if matching_position_found:
                        break
                    if attempt_index < position_check_attempts - 1 and position_check_sleep_seconds > 0:
                        sleep(float(position_check_sleep_seconds))
            if matching_position_found:
                close_result = _order_result_from_client(
                    self._client.place_order(
                        {
                            "account_id": self.credentials.account_id,
                            "symbol": order_request.symbol,
                            "side": _opposite_side(order_request.side),
                            "quantity": _decimal_payload(order_request.quantity),
                            "price": _decimal_payload(order_request.price),
                            "order_type": "market",
                            **contract_payload,
                            **approval_payload,
                            "order_role": "close_position",
                        }
                    )
                )
                if close_result.accepted:
                    close_order_id = close_result.order_id
                    lifecycle.append("close_submitted")
                else:
                    lifecycle.append("close_rejected")
            else:
                lifecycle.append("close_skipped_no_position")

        status = "closed" if close_order_id is not None else ("cancelled" if cancelled else entry_result.status)
        return self._execution_result(
            order_request=order_request,
            submitted_at=submitted_at_utc,
            cancel_requested_at=cancel_requested_at_utc,
            order_notional=order_notional,
            accepted=True,
            status=status,
            reject_reason=None,
            lifecycle=lifecycle,
            submitted_order_id=entry_result.order_id,
            close_order_id=close_order_id,
            cancelled=cancelled,
            diagnostics={
                "broker_name": "ibkr",
                "mode": "paper",
                "manual_approval_id": approval_payload["manual_approval_id"],
                "account_snapshot_status": account_snapshot.status,
            },
        )

    def _execution_result(
        self,
        *,
        order_request: LiveOrderRequest,
        submitted_at: datetime,
        cancel_requested_at: datetime | None,
        order_notional: Decimal,
        accepted: bool,
        status: str,
        reject_reason: str | None,
        lifecycle: list[str],
        submitted_order_id: str | None,
        close_order_id: str | None,
        cancelled: bool,
        diagnostics: dict[str, object],
    ) -> IBKRPaperSandboxOrderExecutionResult:
        return IBKRPaperSandboxOrderExecutionResult(
            accepted=accepted,
            status=status,
            reject_reason=reject_reason,
            lifecycle=lifecycle,
            submitted_at=submitted_at,
            cancel_requested_at=cancel_requested_at,
            symbol=order_request.symbol,
            side=order_request.side,
            quantity=_quantize_money(order_request.quantity),
            price=_quantize_money(order_request.price),
            order_notional=order_notional,
            submitted_order_id=submitted_order_id,
            close_order_id=close_order_id,
            cancelled=cancelled,
            diagnostics=diagnostics,
        )

    def _dry_run_result(
        self,
        *,
        order_request: LiveOrderRequest,
        submitted_at: datetime,
        cancel_requested_at: datetime | None,
        order_notional: Decimal,
        accepted: bool,
        status: str,
        reject_reason: str | None,
        lifecycle: list[str],
        diagnostics: dict[str, object],
    ) -> IBKRPaperSandboxOrderLifecycleDryRun:
        return IBKRPaperSandboxOrderLifecycleDryRun(
            accepted=accepted,
            status=status,
            reject_reason=reject_reason,
            lifecycle=lifecycle,
            submitted_at=submitted_at,
            cancel_requested_at=cancel_requested_at,
            symbol=order_request.symbol,
            side=order_request.side,
            quantity=_quantize_money(order_request.quantity),
            price=_quantize_money(order_request.price),
            order_notional=order_notional,
            diagnostics=diagnostics,
        )

    def place_order_if_allowed(
        self,
        *,
        config: LiveReadinessConfig,
        order_request: LiveOrderRequest,
        routing_request: LiveBrokerRoutingRequest,
        order_type: str = "market",
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> OrderResult:
        readiness_decision = evaluate_live_order_readiness(config, order_request)
        if not readiness_decision.passed:
            return OrderResult(
                order_id="",
                status="rejected",
                accepted=False,
                message=readiness_decision.reject_reason,
            )

        guarded_routing_request = LiveBrokerRoutingRequest(
            broker_name="ibkr",
            credentials_configured=self.is_available,
            manual_approval_id=routing_request.manual_approval_id,
            approval_actor=routing_request.approval_actor,
            approved_at=routing_request.approved_at,
        )
        routing_decision = evaluate_live_broker_routing(
            config,
            readiness_decision,
            guarded_routing_request,
        )
        if not routing_decision.passed:
            return OrderResult(
                order_id="",
                status="rejected",
                accepted=False,
                message=routing_decision.reject_reason,
            )

        if self.credentials is None or self._client is None:
            return OrderResult(
                order_id="",
                status="rejected",
                accepted=False,
                message="broker_credentials_missing",
            )

        payload = {
            "account_id": self.credentials.account_id,
            "symbol": order_request.symbol,
            "side": order_request.side,
            "quantity": _decimal_payload(order_request.quantity),
            "price": _decimal_payload(order_request.price),
            "order_type": order_type,
            "stop_loss": _decimal_payload(stop_loss),
            "take_profit": _decimal_payload(take_profit),
            "manual_approval_id": str(routing_decision.checks["manual_approval_id"]),
            "approval_actor": str(routing_decision.checks["approval_actor"]),
            "approved_at": str(routing_decision.checks["approved_at"]),
        }
        return self._client.place_order(payload)

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError("IBKR paper sandbox cancel routing is not implemented.")

    def get_positions(self) -> list[PositionData]:
        raise NotImplementedError("IBKR paper sandbox position sync is not implemented.")

    def get_account(self) -> AccountData:
        raise NotImplementedError("IBKR paper sandbox account sync is not implemented.")
