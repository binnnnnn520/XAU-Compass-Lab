from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path

import pytest


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "phase1_walk_forward_samples.json"


def test_walk_forward_validation_runs_bar_by_bar_and_reports_metrics() -> None:
    from app.services.phase1_acceptance.walk_forward import load_walk_forward_samples, run_walk_forward_validation

    samples = load_walk_forward_samples(FIXTURE_PATH)
    result = run_walk_forward_validation(samples, buy_threshold=Decimal("0.5200"), sell_threshold=Decimal("0.4800"))

    assert result.sample_count == 12
    assert result.bars_processed == 12
    assert result.total_trades == 12
    assert result.win_rate >= Decimal("0.9000")
    assert result.sharpe_ratio > Decimal("0.5000")
    assert result.max_drawdown <= Decimal("0.0000")
    assert result.equity_curve[0][0].isoformat() == "2026-04-03T00:00:00+00:00"


def test_walk_forward_validation_rejects_unsorted_samples() -> None:
    from app.services.phase1_acceptance.walk_forward import WalkForwardSample, run_walk_forward_validation

    samples = (
        WalkForwardSample(timestamp="2026-04-03T01:00:00Z", probability=Decimal("0.6000"), realized_return=Decimal("0.0100")),
        WalkForwardSample(timestamp="2026-04-03T00:00:00Z", probability=Decimal("0.6000"), realized_return=Decimal("0.0100")),
    )

    with pytest.raises(ValueError, match="sorted"):
        run_walk_forward_validation(samples)


def test_walk_forward_cli_outputs_json() -> None:
    from app.services.phase1_acceptance.walk_forward import run_walk_forward_cli

    stdout = io.StringIO()
    exit_code = run_walk_forward_cli(
        [
            "--samples",
            str(FIXTURE_PATH),
            "--min-sharpe",
            "0.5",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["sample_count"] == 12
    assert Decimal(payload["sharpe_ratio"]) > Decimal("0.5000")
