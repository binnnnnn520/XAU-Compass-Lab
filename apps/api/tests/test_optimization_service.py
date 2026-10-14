from __future__ import annotations

import builtins
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import StrategyRun
from app.services.optimization import (
    BacktestObjectiveConfig,
    OptimizationDependencyError,
    XGBoostParameterCandidate,
    evaluate_backtest_objective,
    sample_rule_strategy_parameters,
    sample_xgboost_parameters,
    run_optuna_search,
)
from app.services.optimization.objective import (
    evaluate_backtest_objective as objective_evaluate_backtest_objective,
    sample_xgboost_parameters as objective_sample_xgboost_parameters,
)


class FakeTrial:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def suggest_int(self, name: str, low: int, high: int) -> int:
        self.calls.append(("int", name))
        values = {
            "n_estimators": 250,
            "max_depth": 5,
        }
        return values[name]

    def suggest_float(self, name: str, low: float, high: float) -> float:
        self.calls.append(("float", name))
        values = {
            "learning_rate": 0.075,
            "positive_sentiment_threshold": 0.25,
            "negative_sentiment_threshold": -0.25,
            "positive_momentum_threshold": 0.0002,
            "negative_momentum_threshold": -0.0002,
        }
        return values[name]


def test_sample_xgboost_parameters_returns_decimal_safe_serializable_values() -> None:
    trial = FakeTrial()

    candidate = sample_xgboost_parameters(trial)

    assert candidate.parameters == {
        "n_estimators": 250,
        "max_depth": 5,
        "learning_rate": Decimal("0.0750"),
    }
    assert candidate.to_strategy_parameters() == {
        "n_estimators": 250,
        "max_depth": 5,
        "learning_rate": "0.0750",
    }


def test_objective_module_exposes_parameter_sampler() -> None:
    candidate = objective_sample_xgboost_parameters(FakeTrial())

    assert candidate.parameters["learning_rate"] == Decimal("0.0750")


def test_sample_rule_strategy_parameters_returns_decimal_safe_thresholds() -> None:
    candidate = sample_rule_strategy_parameters(FakeTrial())

    assert candidate.parameters == {
        "positive_sentiment_threshold": Decimal("0.2500"),
        "negative_sentiment_threshold": Decimal("-0.2500"),
        "positive_momentum_threshold": Decimal("0.0002"),
        "negative_momentum_threshold": Decimal("-0.0002"),
    }
    assert candidate.to_strategy_parameters() == {
        "positive_sentiment_threshold": "0.2500",
        "negative_sentiment_threshold": "-0.2500",
        "positive_momentum_threshold": "0.0002",
        "negative_momentum_threshold": "-0.0002",
    }


def test_run_optuna_search_requires_declared_dependency_when_not_installed(monkeypatch) -> None:
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "optuna":
            raise ImportError("blocked optuna import")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(OptimizationDependencyError, match="optuna>=3.5"):
        run_optuna_search(lambda trial: Decimal("1.0000"), n_trials=1)


def test_run_optuna_search_executes_bounded_study_when_dependency_available() -> None:
    pytest.importorskip("optuna")

    result = run_optuna_search(
        lambda trial: Decimal(str(trial.suggest_int("score", 1, 2))),
        n_trials=2,
    )

    assert result.trial_count == 2
    assert result.best_value in {Decimal("1.0000"), Decimal("2.0000")}
    assert result.best_parameters["score"] in {1, 2}


def test_evaluate_backtest_objective_uses_temporary_strategy_without_mutating_base(db_session) -> None:
    base_strategy = StrategyRun(
        strategy_name="sentiment_momentum_v1",
        version="1.0.0",
        parameters={"lookback_hours": 2, "momentum_bars": 1},
        is_active=True,
    )
    db_session.add(base_strategy)
    db_session.commit()
    captured: dict[str, object] = {}

    def fake_backtest_runner(session, payload, *, persist):
        assert persist is False
        temp_strategy = session.get(StrategyRun, payload.strategy_run_id)
        captured["temp_id"] = temp_strategy.id
        captured["temp_parameters"] = dict(temp_strategy.parameters)
        return SimpleNamespace(
            sharpe_ratio=Decimal("1.234567"),
            total_return=Decimal("0.100000"),
            max_drawdown=Decimal("-0.010000"),
            total_trades=3,
        )

    result = objective_evaluate_backtest_objective(
        db_session,
        BacktestObjectiveConfig(
            base_strategy_run_id=base_strategy.id,
            start_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
            initial_capital=Decimal("1000.00"),
        ),
        XGBoostParameterCandidate(
            parameters={
                "n_estimators": 250,
                "max_depth": 5,
                "learning_rate": Decimal("0.0750"),
            }
        ),
        backtest_runner=fake_backtest_runner,
    )

    db_session.refresh(base_strategy)

    assert result.sharpe_ratio == Decimal("1.234567")
    assert captured["temp_parameters"] == {
        "lookback_hours": 2,
        "momentum_bars": 1,
        "n_estimators": 250,
        "max_depth": 5,
        "learning_rate": "0.0750",
        "optimization": {
            "base_strategy_run_id": str(base_strategy.id),
            "candidate_source": "optuna",
        },
    }
    assert base_strategy.parameters == {"lookback_hours": 2, "momentum_bars": 1}
    assert db_session.get(StrategyRun, captured["temp_id"]) is None
