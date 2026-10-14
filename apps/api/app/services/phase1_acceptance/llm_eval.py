from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, TextIO

from app.models import NewsItem


ALLOWED_SENTIMENTS = {"positive", "negative", "neutral"}
DECIMAL_QUANT = Decimal("0.0001")
DEFAULT_THRESHOLD = Decimal("0.7500")
EVALUATION_MODES = {"recorded", "live"}


@dataclass(frozen=True)
class LLMEvaluationSample:
    sample_id: str
    title: str
    summary: str | None
    content: str | None
    published_at: datetime
    expected_sentiment: str
    recorded_analysis: dict[str, Any] | None


@dataclass(frozen=True)
class LLMEvaluationFailure:
    sample_id: str
    expected_sentiment: str
    actual_sentiment: str


@dataclass(frozen=True)
class LLMEvaluationSummary:
    total: int
    correct: int
    accuracy: Decimal
    threshold: Decimal
    passed: bool
    failures: tuple[LLMEvaluationFailure, ...]
    mode: str = "recorded"


def load_llm_evaluation_samples(path: str | Path) -> tuple[LLMEvaluationSample, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("LLM evaluation fixture must be a JSON array.")

    samples: list[LLMEvaluationSample] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Sample at index {index} must be a JSON object.")
        samples.append(_sample_from_payload(item, index=index))
    if not samples:
        raise ValueError("LLM evaluation fixture must contain at least one sample.")
    return tuple(samples)


def _sample_from_payload(item: dict[str, Any], *, index: int) -> LLMEvaluationSample:
    sample_id = _required_string(item.get("id"), field_name=f"sample[{index}].id")
    title = _required_string(item.get("title"), field_name=f"sample[{index}].title")
    expected = _required_string(
        item.get("expected_sentiment"),
        field_name=f"sample[{index}].expected_sentiment",
    ).lower()
    if expected not in ALLOWED_SENTIMENTS:
        raise ValueError(f"sample[{index}].expected_sentiment must be positive, negative, or neutral.")

    recorded_analysis = item.get("recorded_analysis")
    if recorded_analysis is not None and not isinstance(recorded_analysis, dict):
        raise ValueError(f"sample[{index}].recorded_analysis must be a JSON object.")

    return LLMEvaluationSample(
        sample_id=sample_id,
        title=title,
        summary=_optional_string(item.get("summary"), field_name=f"sample[{index}].summary"),
        content=_optional_string(item.get("content"), field_name=f"sample[{index}].content"),
        published_at=_parse_utc_datetime(
            _required_string(item.get("published_at"), field_name=f"sample[{index}].published_at")
        ),
        expected_sentiment=expected,
        recorded_analysis=recorded_analysis,
    )


def _required_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null.")
    return value


def _parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("published_at must include a timezone.")
    return parsed.astimezone(UTC)


def evaluate_recorded_samples(
    samples: tuple[LLMEvaluationSample, ...],
    *,
    threshold: Decimal = DEFAULT_THRESHOLD,
    require_direct_llm: bool = False,
    mode: str = "recorded",
) -> LLMEvaluationSummary:
    if not samples:
        raise ValueError("At least one evaluation sample is required.")
    if mode not in EVALUATION_MODES:
        raise ValueError("Evaluation mode must be recorded or live.")

    normalized_threshold = threshold.quantize(DECIMAL_QUANT)
    correct = 0
    failures: list[LLMEvaluationFailure] = []
    fallback_seen = False

    for sample in samples:
        actual = _recorded_sentiment(sample, require_direct_llm=require_direct_llm)
        if require_direct_llm and actual.startswith("fallback:"):
            fallback_seen = True
        if actual == sample.expected_sentiment:
            correct += 1
            continue
        failures.append(
            LLMEvaluationFailure(
                sample_id=sample.sample_id,
                expected_sentiment=sample.expected_sentiment,
                actual_sentiment=actual,
            )
        )

    accuracy = (Decimal(correct) / Decimal(len(samples))).quantize(DECIMAL_QUANT)
    return LLMEvaluationSummary(
        total=len(samples),
        correct=correct,
        accuracy=accuracy,
        threshold=normalized_threshold,
        passed=accuracy >= normalized_threshold and not fallback_seen,
        failures=tuple(failures),
        mode=mode,
    )


def _recorded_sentiment(sample: LLMEvaluationSample, *, require_direct_llm: bool = False) -> str:
    if sample.recorded_analysis is None:
        raise ValueError(f"sample {sample.sample_id} does not have recorded_analysis.")
    if require_direct_llm:
        fallback_reason = _recorded_fallback_reason(sample.recorded_analysis)
        if fallback_reason is not None:
            return f"fallback:{fallback_reason}"

    sentiment = sample.recorded_analysis.get("sentiment")
    if not isinstance(sentiment, str):
        raise ValueError(f"sample {sample.sample_id} recorded sentiment must be a string.")
    normalized = sentiment.strip().lower()
    if normalized not in ALLOWED_SENTIMENTS:
        raise ValueError(f"sample {sample.sample_id} recorded sentiment is invalid.")
    return normalized


def _recorded_fallback_reason(recorded_analysis: dict[str, Any]) -> str | None:
    metadata = recorded_analysis.get("metadata")
    if isinstance(metadata, dict) and metadata.get("fallback_from") == "llm":
        reason = metadata.get("fallback_reason")
        return str(reason or "unknown")
    fallback_reason = recorded_analysis.get("fallback_reason")
    if isinstance(fallback_reason, str) and fallback_reason.strip():
        return fallback_reason.strip()
    return None


def record_llm_analyzer_outputs(
    samples: tuple[LLMEvaluationSample, ...],
    analyzer: Any,
    *,
    reuse_direct_recorded: bool = False,
) -> tuple[LLMEvaluationSample, ...]:
    recorded_samples: list[LLMEvaluationSample] = []
    for sample in samples:
        if reuse_direct_recorded and _has_direct_recorded_analysis(sample):
            recorded_samples.append(sample)
            continue
        result = analyzer.analyze(_news_item_from_sample(sample))
        recorded_samples.append(
            replace(
                sample,
                recorded_analysis=_analysis_result_to_payload(result),
            )
        )
    return tuple(recorded_samples)


def merge_recorded_analysis(
    samples: tuple[LLMEvaluationSample, ...],
    recorded_samples: tuple[LLMEvaluationSample, ...],
) -> tuple[LLMEvaluationSample, ...]:
    recorded_by_id = {
        sample.sample_id: sample.recorded_analysis
        for sample in recorded_samples
        if sample.recorded_analysis is not None
    }
    return tuple(
        replace(sample, recorded_analysis=recorded_by_id.get(sample.sample_id, sample.recorded_analysis))
        for sample in samples
    )


def _has_direct_recorded_analysis(sample: LLMEvaluationSample) -> bool:
    return sample.recorded_analysis is not None and _recorded_fallback_reason(sample.recorded_analysis) is None


def _news_item_from_sample(sample: LLMEvaluationSample) -> NewsItem:
    title_hash = hashlib.sha256(sample.sample_id.encode("utf-8")).hexdigest()
    return NewsItem(
        title=sample.title,
        summary=sample.summary,
        content=sample.content,
        published_at=sample.published_at,
        title_hash=title_hash,
        raw_data={"phase1_eval_sample_id": sample.sample_id},
    )


def _analysis_result_to_payload(result: Any) -> dict[str, Any]:
    return {
        "sentiment": result.sentiment,
        "score": _format_decimal(result.score),
        "confidence": _format_decimal(result.confidence),
        "reasoning": result.reasoning,
        "metadata": _json_safe_value(result.metadata),
        "event_tags": [
            {
                "tag_type": tag.tag_type,
                "tag_value": tag.tag_value,
                "relevance_score": _format_decimal(tag.relevance_score),
                "metadata": _json_safe_value(tag.metadata),
            }
            for tag in result.event_tags
        ],
    }


def _format_decimal(value: Decimal) -> str:
    return format(Decimal(str(value)).quantize(DECIMAL_QUANT), "f")


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _format_decimal(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def evaluation_samples_to_payload(samples: tuple[LLMEvaluationSample, ...]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for sample in samples:
        item: dict[str, Any] = {
            "id": sample.sample_id,
            "title": sample.title,
            "summary": sample.summary,
            "content": sample.content,
            "published_at": _format_utc_datetime(sample.published_at),
            "expected_sentiment": sample.expected_sentiment,
        }
        if sample.recorded_analysis is not None:
            item["recorded_analysis"] = sample.recorded_analysis
        payload.append(item)
    return payload


def write_llm_evaluation_samples(path: str | Path, samples: tuple[LLMEvaluationSample, ...]) -> None:
    Path(path).write_text(
        json.dumps(evaluation_samples_to_payload(samples), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _format_utc_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_to_dict(summary: LLMEvaluationSummary) -> dict[str, object]:
    return {
        "mode": summary.mode,
        "total": summary.total,
        "correct": summary.correct,
        "accuracy": format(summary.accuracy, "f"),
        "threshold": format(summary.threshold, "f"),
        "passed": summary.passed,
        "failures": [
            {
                "sample_id": failure.sample_id,
                "expected_sentiment": failure.expected_sentiment,
                "actual_sentiment": failure.actual_sentiment,
            }
            for failure in summary.failures
        ],
    }


def load_env_file(path: str | Path, *, override: bool = True) -> tuple[str, ...]:
    env_path = Path(path)
    loaded_keys: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = _unquote_env_value(value.strip())
        loaded_keys.append(key)
    return tuple(loaded_keys)


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def build_live_llm_analyzer() -> Any:
    from app.config import Settings
    from app.services.llm_analysis import LLMAnalyzer

    return LLMAnalyzer(settings=Settings())


def run_llm_evaluation_cli(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate LLM sentiment outputs for Phase 1 acceptance.")
    parser.add_argument("--samples", required=True, help="Path to a JSON sample fixture.")
    parser.add_argument(
        "--mode",
        choices=sorted(EVALUATION_MODES),
        default="recorded",
        help="Use checked-in recorded outputs or call the configured live LLM provider.",
    )
    parser.add_argument("--threshold", default="0.75", help="Minimum required accuracy as a decimal ratio.")
    parser.add_argument("--env-file", help="Optional .env file to load before live provider evaluation.")
    parser.add_argument("--record-output", help="Optional path where live provider outputs are written as JSON.")
    parser.add_argument(
        "--resume-recorded",
        help="Optional recorded JSON file whose direct provider outputs should be reused before live retries.",
    )
    args = parser.parse_args(argv)

    if args.env_file:
        load_env_file(args.env_file)

    samples = load_llm_evaluation_samples(args.samples)
    if args.mode == "live":
        if args.resume_recorded:
            samples = merge_recorded_analysis(samples, load_llm_evaluation_samples(args.resume_recorded))
        samples = record_llm_analyzer_outputs(
            samples,
            build_live_llm_analyzer(),
            reuse_direct_recorded=bool(args.resume_recorded),
        )
        if args.record_output:
            write_llm_evaluation_samples(args.record_output, samples)
        summary = evaluate_recorded_samples(
            samples,
            threshold=Decimal(str(args.threshold)),
            require_direct_llm=True,
            mode="live",
        )
    else:
        summary = evaluate_recorded_samples(samples, threshold=Decimal(str(args.threshold)))
    output = stdout or sys.stdout
    output.write(json.dumps(summary_to_dict(summary), indent=2, sort_keys=True))
    output.write("\n")
    return 0 if summary.passed else 1


def main() -> None:
    raise SystemExit(run_llm_evaluation_cli())


if __name__ == "__main__":
    main()
