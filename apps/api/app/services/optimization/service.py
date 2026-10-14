from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import StrategyRun
from app.schemas import BacktestCreateRequest
from app.services.backtest_engine import run_backtest


PARAMETER_QUANTIZER = Decimal("0.0001")
ObjectiveValue = Decimal | int | str


class TrialLike(Protocol):
    def suggest_int(self, name: str, low: int, high: int) -> int:
        ...

    def suggest_float(self, name: str, low: float, high: float) -> float:
        ...


class OptimizationDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class XGBoostParameterCandidate:
    parameters: dict[str, int | Decimal]

    def to_strategy_parameters(self) -> dict[str, int | str]:
        strategy_parameters: dict[str, int | str] = {}
        for key, value in self.parameters.items():
            strategy_parameters[key] = format(value, "f") if isinstance(value, Decimal) else value
        return strategy_parameters


@dataclass(frozen=True)
class OptimizationSearchResult:
    best_value: Decimal
    best_parameters: dict[str, int | str]
    trial_count: int


@dataclass(frozen=True)
class BacktestObjectiveConfig:
    base_strategy_run_id: UUID
    start_date: date
    end_date: date
    initial_capital: Decimal
    slippage_bps: int = 0
    commission_bps: int = 0


@dataclass(frozen=True)
class BacktestObjectiveResult:
    candidate: XGBoostParameterCandidate
    sharpe_ratio: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    total_trades: int


def _quantize_parameter(value: Decimal) -> Decimal:
    return value.quantize(PARAMETER_QUANTIZER, rounding=ROUND_HALF_UP)


def _normalize_objective_value(value: ObjectiveValue) -> Decimal:
    return _quantize_parameter(Decimal(str(value)))


def _normalize_best_parameters(parameters: dict[str, Any]) -> dict[str, int | str]:
    normalized: dict[str, int | str] = {}
    for key, value in parameters.items():
        if isinstance(value, int):
            normalized[key] = value
        elif isinstance(value, float):
            normalized[key] = format(_quantize_parameter(Decimal(str(value))), "f")
        elif isinstance(value, Decimal):
            normalized[key] = format(_quantize_parameter(value), "f")
        else:
            normalized[key] = str(value)
    return normalized


def _decimal_metric(value: object) -> Decimal:
    return Decimal("0") if value is None else Decimal(str(value))


def _objective_parameters(base_strategy: StrategyRun, candidate: XGBoostParameterCandidate) -> dict[str, object]:
    parameters: dict[str, object] = dict(base_strategy.parameters or {})
    parameters.update(candidate.to_strategy_parameters())
    parameters["optimization"] = {
        "base_strategy_run_id": str(base_strategy.id),
        "candidate_source": "optuna",
    }
    return parameters


def sample_xgboost_parameters(trial: TrialLike) -> XGBoostParameterCandidate:
    learning_rate = _quantize_parameter(Decimal(str(trial.suggest_float("learning_rate", 0.01, 0.3))))
    return XGBoostParameterCandidate(
        parameters={
            "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": learning_rate,
        }
    )


def sample_rule_strategy_parameters(trial: TrialLike) -> XGBoostParameterCandidate:
    return XGBoostParameterCandidate(
        parameters={
            "positive_sentiment_threshold": _quantize_parameter(
                Decimal(str(trial.suggest_float("positive_sentiment_threshold", 0.1, 0.9)))
            ),
            "negative_sentiment_threshold": _quantize_parameter(
                Decimal(str(trial.suggest_float("negative_sentiment_threshold", -0.9, -0.1)))
            ),
            "positive_momentum_threshold": _quantize_parameter(
                Decimal(str(trial.suggest_float("positive_momentum_threshold", 0.00001, 0.01)))
            ),
            "negative_momentum_threshold": _quantize_parameter(
                Decimal(str(trial.suggest_float("negative_momentum_threshold", -0.01, -0.00001)))
            ),
        }
    )


def evaluate_backtest_objective(
    session: Session,
    config: BacktestObjectiveConfig,
    candidate: XGBoostParameterCandidate,
    *,
    backtest_runner: Callable[..., Any] = run_backtest,
) -> BacktestObjectiveResult:
    base_strategy = session.get(StrategyRun, config.base_strategy_run_id)
    if base_strategy is None:
        raise ValueError(f"strategy run not found: {config.base_strategy_run_id}")

    temp_strategy = StrategyRun(
        strategy_name=base_strategy.strategy_name,
        version="phase4-opt",
        parameters=_objective_parameters(base_strategy, candidate),
        description=f"Temporary Phase 4 optimization candidate for {base_strategy.id}",
        is_active=False,
    )
    session.add(temp_strategy)
    session.flush()
    try:
        result = backtest_runner(
            session,
            BacktestCreateRequest(
                strategy_run_id=temp_strategy.id,
                start_date=config.start_date,
                end_date=config.end_date,
                initial_capital=config.initial_capital,
                slippage_bps=config.slippage_bps,
                commission_bps=config.commission_bps,
            ),
            persist=False,
        )
    finally:
        session.delete(temp_strategy)
        session.flush()

    return BacktestObjectiveResult(
        candidate=candidate,
        sharpe_ratio=_decimal_metric(getattr(result, "sharpe_ratio", None)),
        total_return=_decimal_metric(getattr(result, "total_return", None)),
        max_drawdown=_decimal_metric(getattr(result, "max_drawdown", None)),
        total_trades=int(getattr(result, "total_trades", 0) or 0),
    )


def run_optuna_search(
    objective: Callable[[Any], ObjectiveValue],
    *,
    n_trials: int,
    direction: Literal["maximize", "minimize"] = "maximize",
    study_name: str | None = None,
) -> OptimizationSearchResult:
    if n_trials <= 0:
        raise ValueError("n_trials must be positive")

    try:
        import optuna
    except ImportError as exc:
        raise OptimizationDependencyError(
            "Phase 4 optimization requires optuna>=3.5 installed in the gold-agent environment."
        ) from exc

    study = optuna.create_study(direction=direction, study_name=study_name)

    def _objective(trial: Any) -> float:
        return float(_normalize_objective_value(objective(trial)))

    study.optimize(_objective, n_trials=n_trials)
    return OptimizationSearchResult(
        best_value=_normalize_objective_value(study.best_value),
        best_parameters=_normalize_best_parameters(dict(study.best_params)),
        trial_count=len(study.trials),
    )
