from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.services.broker.ibkr_paper_runtime_verification import (
    build_runtime_verification_config,
    run_runtime_verification,
)


class FakeRuntimeBroker:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute_paper_order_lifecycle_if_allowed(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Result",
            (),
            {
                "accepted": True,
                "status": "cancelled",
                "reject_reason": None,
                "lifecycle": ["submitted", "cancel_requested", "cancelled"],
                "submitted_order_id": "9001",
                "close_order_id": None,
                "cancelled": True,
                "submitted_at": kwargs["submitted_at"],
                "cancel_requested_at": kwargs["cancel_requested_at"],
                "symbol": kwargs["order_request"].symbol,
                "side": kwargs["order_request"].side,
                "quantity": kwargs["order_request"].quantity,
                "price": kwargs["order_request"].price,
                "order_notional": Decimal("230.00000000"),
            },
        )()


def _env(*, enabled: str = "true") -> dict[str, str]:
    return {
        "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED": enabled,
        "IBKR_PAPER_SANDBOX_MODE": "paper",
        "IBKR_PAPER_SANDBOX_HOST": "127.0.0.1",
        "IBKR_PAPER_SANDBOX_PORT": "7497",
        "IBKR_PAPER_SANDBOX_CLIENT_ID": "101",
        "IBKR_PAPER_SANDBOX_ACCOUNT_ID": "DU123456",
        "IBKR_PAPER_ORDER_SYMBOL": "XAUUSD",
        "IBKR_PAPER_ORDER_SIDE": "BUY",
        "IBKR_PAPER_ORDER_QUANTITY": "0.10000000",
        "IBKR_PAPER_ORDER_PRICE": "2300.00000000",
        "IBKR_PAPER_ORDER_SEC_TYPE": "CMDTY",
        "IBKR_PAPER_ORDER_EXCHANGE": "SMART",
        "IBKR_PAPER_ORDER_CURRENCY": "USD",
        "IBKR_PAPER_MANUAL_APPROVAL_ID": "approval-runtime-1",
        "IBKR_PAPER_MANUAL_APPROVAL_ACTOR": "phase5_admin",
        "IBKR_PAPER_MANUAL_APPROVED_AT": "2026-05-01T12:00:00+00:00",
    }


def test_runtime_verification_config_refuses_when_execution_flag_disabled() -> None:
    config = build_runtime_verification_config(_env(enabled="false"))

    assert config.enabled is False
    assert config.reject_reason == "paper_order_execution_disabled"


def test_runtime_verification_config_rejects_naive_approval_time() -> None:
    env = {**_env(), "IBKR_PAPER_MANUAL_APPROVED_AT": "2026-05-01T12:00:00"}

    try:
        build_runtime_verification_config(env)
    except ValueError as exc:
        assert "UTC-aware" in str(exc)
    else:
        raise AssertionError("naive manual approval timestamps must be rejected")


def test_runtime_verification_uses_guarded_broker_and_redacts_account_id() -> None:
    broker = FakeRuntimeBroker()
    generated_at = datetime(2026, 5, 1, 12, 1, tzinfo=UTC)

    evidence = run_runtime_verification(
        environ=_env(),
        broker_factory=lambda credentials, client: broker,
        generated_at=generated_at,
    )

    assert evidence["accepted"] is True
    assert evidence["status"] == "cancelled"
    assert evidence["lifecycle"] == ["submitted", "cancel_requested", "cancelled"]
    assert evidence["submitted_order_id"] == "9001"
    assert evidence["account_id"] == "redacted"
    assert "DU123456" not in str(evidence)
    assert broker.calls[0]["execution_enabled"] is True
    assert broker.calls[0]["order_request"].quantity == Decimal("0.10000000")
    assert broker.calls[0]["routing_request"].manual_approval_id == "approval-runtime-1"


def test_runtime_verification_can_run_market_entry_without_immediate_cancel_for_close_evidence() -> None:
    broker = FakeRuntimeBroker()
    generated_at = datetime(2026, 5, 1, 12, 2, tzinfo=UTC)
    env = {
        **_env(),
        "IBKR_PAPER_CLOSE_EXISTING_POSITION": "true",
        "IBKR_PAPER_ORDER_TYPE": "market",
        "IBKR_PAPER_CANCEL_AFTER_SUBMIT": "false",
    }

    config = build_runtime_verification_config(env)
    evidence = run_runtime_verification(
        environ=env,
        broker_factory=lambda credentials, client: broker,
        generated_at=generated_at,
    )

    assert config.order_type == "market"
    assert config.cancel_after_submit is False
    assert evidence["account_id"] == "redacted"
    assert broker.calls[0]["cancel_requested_at"] is None
    assert broker.calls[0]["close_existing_position"] is True
    assert broker.calls[0]["order_type"] == "market"
