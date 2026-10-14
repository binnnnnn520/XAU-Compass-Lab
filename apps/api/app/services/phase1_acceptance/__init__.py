from __future__ import annotations

from typing import Any


__all__ = [
    "LLMEvaluationFailure",
    "LLMEvaluationSample",
    "LLMEvaluationSummary",
    "build_live_llm_analyzer",
    "evaluate_recorded_samples",
    "evaluation_samples_to_payload",
    "load_env_file",
    "load_llm_evaluation_samples",
    "merge_recorded_analysis",
    "record_llm_analyzer_outputs",
    "run_llm_evaluation_cli",
    "summary_to_dict",
    "write_llm_evaluation_samples",
    "WalkForwardResult",
    "WalkForwardSample",
    "load_walk_forward_samples",
    "run_walk_forward_cli",
    "run_walk_forward_validation",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name in {
        "WalkForwardResult",
        "WalkForwardSample",
        "load_walk_forward_samples",
        "run_walk_forward_cli",
        "run_walk_forward_validation",
    }:
        from app.services.phase1_acceptance import walk_forward

        return getattr(walk_forward, name)
    from app.services.phase1_acceptance import llm_eval

    return getattr(llm_eval, name)
