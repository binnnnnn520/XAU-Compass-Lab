from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "phase1_llm_eval_samples.json"
PROVIDER_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "phase1_llm_eval_provider_samples.json"
EMPTY_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "phase1_llm_eval_empty.json"
INVALID_SENTIMENT_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "phase1_llm_eval_invalid_sentiment.json"
)


def test_load_llm_evaluation_samples_from_fixture() -> None:
    from app.services.phase1_acceptance.llm_eval import load_llm_evaluation_samples

    samples = load_llm_evaluation_samples(FIXTURE_PATH)

    assert len(samples) == 4
    assert samples[0].sample_id == "fed-rate-cut-001"
    assert samples[0].expected_sentiment == "positive"
    assert samples[0].recorded_analysis["sentiment"] == "positive"
    assert samples[0].published_at.isoformat() == "2026-04-01T10:00:00+00:00"


def test_load_llm_evaluation_samples_accepts_labeled_provider_fixture_without_recorded_outputs() -> None:
    from app.services.phase1_acceptance.llm_eval import load_llm_evaluation_samples

    samples = load_llm_evaluation_samples(PROVIDER_FIXTURE_PATH)

    assert len(samples) >= 12
    assert samples[0].sample_id == "provider-fed-cuts-001"
    assert samples[0].expected_sentiment == "positive"
    assert samples[0].recorded_analysis is None


def test_evaluate_recorded_samples_reports_accuracy_and_failures() -> None:
    from app.services.phase1_acceptance.llm_eval import (
        evaluate_recorded_samples,
        load_llm_evaluation_samples,
    )

    samples = load_llm_evaluation_samples(FIXTURE_PATH)
    summary = evaluate_recorded_samples(samples, threshold=Decimal("0.7500"))

    assert summary.total == 4
    assert summary.correct == 3
    assert summary.accuracy == Decimal("0.7500")
    assert summary.threshold == Decimal("0.7500")
    assert summary.passed is True
    assert len(summary.failures) == 1
    assert summary.failures[0].sample_id == "rangebound-004"
    assert summary.failures[0].expected_sentiment == "neutral"
    assert summary.failures[0].actual_sentiment == "negative"


def test_evaluate_recorded_samples_fails_when_threshold_is_not_met() -> None:
    from app.services.phase1_acceptance.llm_eval import (
        evaluate_recorded_samples,
        load_llm_evaluation_samples,
    )

    samples = load_llm_evaluation_samples(FIXTURE_PATH)
    summary = evaluate_recorded_samples(samples, threshold=Decimal("0.8000"))

    assert summary.accuracy == Decimal("0.7500")
    assert summary.passed is False


def test_record_llm_analyzer_outputs_converts_labeled_samples_to_recorded_outputs() -> None:
    from app.services.llm_analysis import AnalysisResult, EventTagResult
    from app.services.phase1_acceptance.llm_eval import (
        evaluate_recorded_samples,
        load_llm_evaluation_samples,
        record_llm_analyzer_outputs,
    )

    class StubAnalyzer:
        analyzer_type = "llm_stub"

        def __init__(self) -> None:
            self.seen: list[tuple[str, datetime]] = []

        def analyze(self, item: Any) -> AnalysisResult:
            self.seen.append((item.title, item.published_at))
            return AnalysisResult(
                analyzer_type=self.analyzer_type,
                sentiment="positive",
                score=Decimal("0.6200"),
                confidence=Decimal("0.8100"),
                reasoning="Stubbed provider output.",
                metadata={"provider": "stub", "model": "fixture"},
                event_tags=(
                    EventTagResult(
                        tag_type="monetary_policy",
                        tag_value="fed_rate_cut",
                        relevance_score=Decimal("0.9000"),
                        metadata={"source": "stub"},
                    ),
                ),
            )

    samples = load_llm_evaluation_samples(PROVIDER_FIXTURE_PATH)[:1]
    recorded_samples = record_llm_analyzer_outputs(samples, StubAnalyzer())
    summary = evaluate_recorded_samples(recorded_samples, require_direct_llm=True)

    assert recorded_samples[0].recorded_analysis is not None
    assert recorded_samples[0].recorded_analysis["sentiment"] == "positive"
    assert recorded_samples[0].recorded_analysis["score"] == "0.6200"
    assert recorded_samples[0].recorded_analysis["metadata"]["provider"] == "stub"
    assert recorded_samples[0].recorded_analysis["event_tags"][0]["relevance_score"] == "0.9000"
    assert summary.passed is True


def test_record_llm_analyzer_outputs_reuses_existing_direct_recorded_outputs() -> None:
    from app.services.llm_analysis import AnalysisResult
    from app.services.phase1_acceptance.llm_eval import (
        load_llm_evaluation_samples,
        record_llm_analyzer_outputs,
    )

    class CountingAnalyzer:
        analyzer_type = "llm_stub"

        def __init__(self) -> None:
            self.calls = 0

        def analyze(self, item: Any) -> AnalysisResult:
            self.calls += 1
            return AnalysisResult(
                analyzer_type=self.analyzer_type,
                sentiment="negative",
                score=Decimal("-0.6000"),
                confidence=Decimal("0.8000"),
                reasoning="Only missing or fallback samples should be retried.",
                metadata={"provider": "stub", "model": "fixture"},
                event_tags=(),
            )

    samples = load_llm_evaluation_samples(PROVIDER_FIXTURE_PATH)[:2]
    direct_recorded = replace(
        samples[0],
        recorded_analysis={
            "sentiment": "positive",
            "score": "0.6000",
            "confidence": "0.8000",
            "reasoning": "Existing direct provider output.",
            "metadata": {"provider": "stub", "model": "fixture"},
            "event_tags": [],
        },
    )
    analyzer = CountingAnalyzer()

    recorded_samples = record_llm_analyzer_outputs(
        (direct_recorded, samples[1]),
        analyzer,
        reuse_direct_recorded=True,
    )

    assert analyzer.calls == 1
    assert recorded_samples[0].recorded_analysis == direct_recorded.recorded_analysis
    assert recorded_samples[1].recorded_analysis["sentiment"] == "negative"


def test_merge_recorded_analysis_overlays_existing_outputs_by_sample_id() -> None:
    from app.services.phase1_acceptance.llm_eval import (
        load_llm_evaluation_samples,
        merge_recorded_analysis,
    )

    samples = load_llm_evaluation_samples(PROVIDER_FIXTURE_PATH)[:1]
    recorded_sample = replace(
        samples[0],
        recorded_analysis={
            "sentiment": "positive",
            "score": "0.6000",
            "confidence": "0.8000",
            "reasoning": "Existing provider output.",
            "metadata": {"provider": "stub", "model": "fixture"},
            "event_tags": [],
        },
    )

    merged = merge_recorded_analysis(samples, (recorded_sample,))

    assert merged[0].recorded_analysis == recorded_sample.recorded_analysis


def test_evaluate_recorded_samples_rejects_llm_fallback_when_direct_provider_required() -> None:
    from app.services.llm_analysis import AnalysisResult
    from app.services.phase1_acceptance.llm_eval import (
        evaluate_recorded_samples,
        load_llm_evaluation_samples,
        record_llm_analyzer_outputs,
    )

    class FallbackAnalyzer:
        analyzer_type = "rule_based"

        def analyze(self, item: Any) -> AnalysisResult:
            return AnalysisResult(
                analyzer_type=self.analyzer_type,
                sentiment="positive",
                score=Decimal("0.5000"),
                confidence=Decimal("0.7000"),
                reasoning="Fallback output must not satisfy live LLM acceptance.",
                metadata={"fallback_from": "llm", "fallback_reason": "missing_api_key"},
                event_tags=(),
            )

    samples = load_llm_evaluation_samples(PROVIDER_FIXTURE_PATH)[:1]
    recorded_samples = record_llm_analyzer_outputs(samples, FallbackAnalyzer())
    summary = evaluate_recorded_samples(recorded_samples, require_direct_llm=True)

    assert summary.correct == 0
    assert summary.passed is False
    assert summary.failures[0].actual_sentiment == "fallback:missing_api_key"


def test_direct_llm_requirement_fails_run_when_any_fallback_occurs_even_if_accuracy_threshold_is_met() -> None:
    from app.services.llm_analysis import AnalysisResult
    from app.services.phase1_acceptance.llm_eval import (
        evaluate_recorded_samples,
        load_llm_evaluation_samples,
        record_llm_analyzer_outputs,
    )

    class PartiallyFallbackAnalyzer:
        analyzer_type = "mixed"

        def __init__(self) -> None:
            self.calls = 0

        def analyze(self, item: Any) -> AnalysisResult:
            self.calls += 1
            if self.calls == 1:
                return AnalysisResult(
                    analyzer_type="llm_stub",
                    sentiment="positive",
                    score=Decimal("0.6000"),
                    confidence=Decimal("0.8000"),
                    reasoning="Direct provider output.",
                    metadata={"provider": "stub", "model": "fixture"},
                    event_tags=(),
                )
            return AnalysisResult(
                analyzer_type="rule_based",
                sentiment="positive",
                score=Decimal("0.5000"),
                confidence=Decimal("0.7000"),
                reasoning="Fallback output.",
                metadata={"fallback_from": "llm", "fallback_reason": "llm_analysis_failed"},
                event_tags=(),
            )

    samples = load_llm_evaluation_samples(PROVIDER_FIXTURE_PATH)[:2]
    recorded_samples = record_llm_analyzer_outputs(samples, PartiallyFallbackAnalyzer())
    summary = evaluate_recorded_samples(
        recorded_samples,
        threshold=Decimal("0.5000"),
        require_direct_llm=True,
        mode="live",
    )

    assert summary.accuracy == Decimal("0.5000")
    assert summary.passed is False


def test_llm_eval_cli_outputs_json_and_zero_exit_for_passing_fixture() -> None:
    from app.services.phase1_acceptance.llm_eval import run_llm_evaluation_cli

    stdout = io.StringIO()
    exit_code = run_llm_evaluation_cli(
        [
            "--samples",
            str(FIXTURE_PATH),
            "--threshold",
            "0.75",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["accuracy"] == "0.7500"
    assert payload["threshold"] == "0.7500"
    assert payload["total"] == 4
    assert payload["correct"] == 3
    assert payload["failures"][0]["sample_id"] == "rangebound-004"


def test_llm_eval_cli_returns_nonzero_when_threshold_fails() -> None:
    from app.services.phase1_acceptance.llm_eval import run_llm_evaluation_cli

    stdout = io.StringIO()
    exit_code = run_llm_evaluation_cli(
        [
            "--samples",
            str(FIXTURE_PATH),
            "--threshold",
            "0.80",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 1
    assert payload["passed"] is False
    assert payload["accuracy"] == "0.7500"


def test_llm_eval_cli_live_mode_records_provider_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.llm_analysis import AnalysisResult
    from app.services.phase1_acceptance import llm_eval

    class StubAnalyzer:
        analyzer_type = "llm_stub"

        def analyze(self, item: Any) -> AnalysisResult:
            return AnalysisResult(
                analyzer_type=self.analyzer_type,
                sentiment="positive",
                score=Decimal("0.6000"),
                confidence=Decimal("0.8000"),
                reasoning="Stubbed live provider output.",
                metadata={"provider": "stub", "model": "fixture"},
                event_tags=(),
            )

    monkeypatch.setattr(llm_eval, "build_live_llm_analyzer", lambda: StubAnalyzer())
    stdout = io.StringIO()
    recorded_path = Path(__file__).resolve().parent / "fixtures" / "phase1_llm_eval_live_cli_recorded_test.json"

    try:
        exit_code = llm_eval.run_llm_evaluation_cli(
            [
                "--samples",
                str(PROVIDER_FIXTURE_PATH),
                "--mode",
                "live",
                "--threshold",
                "0.75",
                "--record-output",
                str(recorded_path),
            ],
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        recorded_payload = json.loads(recorded_path.read_text(encoding="utf-8"))
    finally:
        recorded_path.unlink(missing_ok=True)

    assert exit_code == 1
    assert payload["mode"] == "live"
    assert payload["accuracy"] == "0.4167"
    assert len(recorded_payload) >= 12
    assert recorded_payload[0]["recorded_analysis"]["metadata"]["provider"] == "stub"


def test_load_llm_evaluation_samples_rejects_empty_fixture() -> None:
    from app.services.phase1_acceptance.llm_eval import load_llm_evaluation_samples

    with pytest.raises(ValueError, match="at least one sample"):
        load_llm_evaluation_samples(EMPTY_FIXTURE_PATH)


def test_load_llm_evaluation_samples_rejects_invalid_sentiment() -> None:
    from app.services.phase1_acceptance.llm_eval import load_llm_evaluation_samples

    with pytest.raises(ValueError, match="expected_sentiment"):
        load_llm_evaluation_samples(INVALID_SENTIMENT_FIXTURE_PATH)
