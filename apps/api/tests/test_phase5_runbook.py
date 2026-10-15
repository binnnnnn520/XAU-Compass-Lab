from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_phase5_live_readiness_sop_documents_required_safety_and_compliance() -> None:
    runbook = REPO_ROOT / "docs" / "operations" / "broker_safety.md"

    content = runbook.read_text(encoding="utf-8")
    lower_content = content.lower()

    assert "paper account" in lower_content
    assert "blocked placeholder" in lower_content
    assert "kill switch" in lower_content
    assert "manual_approval_required" in content
    assert "daily notional" in lower_content
    assert "max_initial_capital_fraction" in content
    assert "0.0100" in content
    assert "PHASE5_OBSERVATION_COLLECTION_ENABLED=false" in content
    assert "PHASE5_EVIDENCE_WINDOW_STARTED=false" in content
    assert "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false" in content
    assert "5 years" in lower_content
    assert "audit_logs append-only" in lower_content
    assert "do not configure real broker credentials by default" in lower_content
    assert "/api/v1/live/emergency-stop" in content


def test_phase5_server_gray_release_runbook_documents_continuous_window_runtime() -> None:
    runbook = REPO_ROOT / "docs" / "operations" / "paper_observation.md"

    content = runbook.read_text(encoding="utf-8")
    lower_content = content.lower()

    assert "utc" in lower_content
    assert "api" in lower_content
    assert "worker" in lower_content
    assert "beat" in lower_content
    assert "ibkr gateway" in lower_content or "tws" in lower_content
    assert "PHASE5_OBSERVATION_COLLECTION_ENABLED=true" in content
    assert "PHASE5_EVIDENCE_WINDOW_STARTED=true" in content
    assert "/api/v1/live/gray-release-report" in content
    assert "/api/v1/live/emergency-stop" in content


def test_phase5_close_position_verification_runbook_documents_supervised_flow() -> None:
    runbook = REPO_ROOT / "docs" / "operations" / "ibkr_paper_verification.md"

    content = runbook.read_text(encoding="utf-8")
    lower_content = content.lower()

    assert "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=true" in content
    assert "IBKR_PAPER_CLOSE_EXISTING_POSITION=true" in content
    assert "IBKR_PAPER_ORDER_TYPE=market" in content
    assert "IBKR_PAPER_CANCEL_AFTER_SUBMIT=false" in content
    assert "IBKR_PAPER_MANUAL_APPROVAL_ID" in content
    assert "IBKR_PAPER_MANUAL_APPROVAL_ACTOR" in content
    assert "IBKR_PAPER_MANUAL_APPROVED_AT" in content
    assert "reqopenorders" in lower_content
    assert "reqpositions" in lower_content
    assert "close_order_id" in content
    assert "finally" in content
    assert "$env:PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED='false'" in content
    assert "status='closed'" in content or 'status="closed"' in content
