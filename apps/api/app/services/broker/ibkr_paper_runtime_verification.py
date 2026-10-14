from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.services.broker.ibkr_broker import (
    IBKRPaperSandboxBroker,
    IBKRPaperSandboxCredentials,
    IBKRPaperSandboxIBAPIClient,
)
from app.services.live_readiness import LiveBrokerRoutingRequest, LiveOrderRequest, load_live_readiness_config


@dataclass(frozen=True)
class RuntimeVerificationConfig:
    enabled: bool
    reject_reason: str | None
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    approved_at: datetime | None
    approval_actor: str | None
    manual_approval_id: str | None
    close_existing_position: bool
    order_type: str
    cancel_after_submit: bool


def _coerce_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _require_utc(value: str, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be a UTC-aware datetime.")
    return parsed.astimezone(UTC)


def build_runtime_verification_config(environ: Mapping[str, str] | None = None) -> RuntimeVerificationConfig:
    env = os.environ if environ is None else environ
    enabled = _coerce_bool(env.get("PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED"))
    if not enabled:
        return RuntimeVerificationConfig(
            enabled=False,
            reject_reason="paper_order_execution_disabled",
            symbol="",
            side="",
            quantity=Decimal("0.00000000"),
            price=Decimal("0.00000000"),
            approved_at=None,
            approval_actor=None,
            manual_approval_id=None,
            close_existing_position=False,
            order_type="limit",
            cancel_after_submit=True,
        )

    approved_at = _require_utc(env["IBKR_PAPER_MANUAL_APPROVED_AT"], "IBKR_PAPER_MANUAL_APPROVED_AT")
    return RuntimeVerificationConfig(
        enabled=True,
        reject_reason=None,
        symbol=env.get("IBKR_PAPER_ORDER_SYMBOL", "XAUUSD").strip(),
        side=env.get("IBKR_PAPER_ORDER_SIDE", "BUY").strip().upper(),
        quantity=Decimal(env.get("IBKR_PAPER_ORDER_QUANTITY", "0.10000000")),
        price=Decimal(env.get("IBKR_PAPER_ORDER_PRICE", "2300.00000000")),
        approved_at=approved_at,
        approval_actor=env.get("IBKR_PAPER_MANUAL_APPROVAL_ACTOR", "").strip(),
        manual_approval_id=env.get("IBKR_PAPER_MANUAL_APPROVAL_ID", "").strip(),
        close_existing_position=_coerce_bool(env.get("IBKR_PAPER_CLOSE_EXISTING_POSITION")),
        order_type=env.get("IBKR_PAPER_ORDER_TYPE", "limit").strip().lower() or "limit",
        cancel_after_submit=_coerce_bool(env.get("IBKR_PAPER_CANCEL_AFTER_SUBMIT", "true")),
    )


def run_runtime_verification(
    *,
    environ: Mapping[str, str] | None = None,
    broker_factory: Callable[[IBKRPaperSandboxCredentials, IBKRPaperSandboxIBAPIClient], Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    generated_at_utc = (generated_at or datetime.now(UTC)).astimezone(UTC)
    config = build_runtime_verification_config(env)
    if not config.enabled:
        return {
            "accepted": False,
            "status": "rejected",
            "reject_reason": config.reject_reason,
            "generated_at": generated_at_utc.isoformat(),
        }

    credentials = IBKRPaperSandboxCredentials.from_env(env)
    if credentials is None:
        return {
            "accepted": False,
            "status": "rejected",
            "reject_reason": "broker_credentials_missing",
            "generated_at": generated_at_utc.isoformat(),
        }

    client = IBKRPaperSandboxIBAPIClient(
        credentials=credentials,
        expected_account_id=credentials.account_id,
        order_execution_enabled=True,
    )
    broker = (
        broker_factory(credentials, client)
        if broker_factory is not None
        else IBKRPaperSandboxBroker(client=client, credentials=credentials, environ=env)
    )
    live_config = load_live_readiness_config(
        {
            "live": {
                "enabled": True,
                "kill_switch_enabled": False,
                "daily_notional_limit": "10000.00000000",
                "max_initial_capital_fraction": "0.0100",
                "real_broker_routing_enabled": True,
            }
        }
    )
    order_request = LiveOrderRequest(
        symbol=config.symbol,
        side=config.side,  # type: ignore[arg-type]
        quantity=config.quantity,
        price=config.price,
        confidence=Decimal("0.9500"),
        daily_notional_so_far=Decimal("0.00000000"),
        total_equity=Decimal("100000.00000000"),
    )
    routing_request = LiveBrokerRoutingRequest(
        broker_name="ibkr",
        credentials_configured=True,
        manual_approval_id=config.manual_approval_id,
        approval_actor=config.approval_actor,
        approved_at=config.approved_at,
    )
    result = broker.execute_paper_order_lifecycle_if_allowed(
        execution_enabled=True,
        config=live_config,
        order_request=order_request,
        routing_request=routing_request,
        submitted_at=generated_at_utc,
        cancel_requested_at=generated_at_utc if config.cancel_after_submit else None,
        close_existing_position=config.close_existing_position,
        order_type=config.order_type,
    )
    return {
        "accepted": result.accepted,
        "status": result.status,
        "reject_reason": result.reject_reason,
        "lifecycle": result.lifecycle,
        "submitted_order_id": result.submitted_order_id,
        "close_order_id": result.close_order_id,
        "cancelled": result.cancelled,
        "generated_at": generated_at_utc.isoformat(),
        "account_id": "redacted",
        "symbol": result.symbol,
        "side": result.side,
        "quantity": format(result.quantity, "f"),
        "price": format(result.price, "f"),
        "order_notional": format(result.order_notional, "f"),
    }


def main() -> int:
    evidence = run_runtime_verification()
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence.get("accepted") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
