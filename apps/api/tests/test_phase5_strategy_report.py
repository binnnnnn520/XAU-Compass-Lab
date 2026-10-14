from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.services.compliance.strategy_report import (
    CapitalAllocationDecision,
    StrategyBacktestEvidence,
    StrategyReportContext,
    build_strategy_report_markdown,
    build_strategy_report_template,
)


def _backtest_evidence() -> StrategyBacktestEvidence:
    return StrategyBacktestEvidence(
        command="python -m app.services.phase1_acceptance.walk_forward --samples phase5.json",
        start_at=datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 4, 30, 0, 0, tzinfo=UTC),
        sample_count=720,
        sharpe_ratio=Decimal("0.8200"),
        max_drawdown=Decimal("0.0800"),
        total_return=Decimal("0.1200"),
        win_rate=Decimal("0.5600"),
    )


def test_strategy_report_template_lists_required_phase5_sections() -> None:
    template = build_strategy_report_template()

    assert "## Strategy Identity" in template
    assert "## Backtest Evidence" in template
    assert "## Gray-Release Evidence" in template
    assert "## Live-Readiness Decisions" in template
    assert "## Capital Allocation Changes" in template
    assert "## Retention And Audit Evidence" in template


def test_strategy_report_markdown_serializes_utc_decimal_and_capital_decisions() -> None:
    context = StrategyReportContext(
        strategy_name="ensemble_v1",
        strategy_version="4.0.0",
        generated_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        generated_by="phase5_admin",
        backtest=_backtest_evidence(),
        gray_release_summary={
            "observation_count": 12,
            "running_days": Decimal("0.5000"),
            "sharpe_deviation": Decimal("0.0500"),
            "risk_event_count": 0,
            "acceptance_ready": False,
        },
        capital_allocation_decisions=(
            CapitalAllocationDecision(
                decided_at=datetime(2026, 5, 1, 9, 30, tzinfo=UTC),
                actor="phase5_admin",
                old_fraction=Decimal("0.0000"),
                new_fraction=Decimal("0.0100"),
                reason="begin supervised paper/live gray-release dry run",
                audit_log_id="audit-1",
            ),
        ),
        live_readiness_decisions=("kill_switch_enabled remains true",),
    )

    report = build_strategy_report_markdown(context)

    assert "# Strategy Report: ensemble_v1 4.0.0" in report
    assert "Generated at: 2026-05-01T10:00:00+00:00" in report
    assert "Sharpe ratio: 0.8200" in report
    assert "Max drawdown: 0.0800" in report
    assert "new_fraction=0.0100" in report
    assert "decided_at=2026-05-01T09:30:00+00:00" in report
    assert "sharpe_deviation=0.0500" in report
    assert "audit_logs append-only" in report
    assert "20260501_0012" in report


def test_strategy_report_rejects_naive_datetimes() -> None:
    context = StrategyReportContext(
        strategy_name="ensemble_v1",
        strategy_version="4.0.0",
        generated_at=datetime(2026, 5, 1, 10, 0),
        generated_by="phase5_admin",
        backtest=_backtest_evidence(),
    )

    with pytest.raises(ValueError, match="UTC-aware"):
        build_strategy_report_markdown(context)
