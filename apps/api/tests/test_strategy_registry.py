from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import pickle
from pathlib import Path
import sys


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.models import ModelVersion, StrategyRun
from app.services.feature_engine import FeatureVector
from app.services.signal_engine import ModelRegistry, RuleStrategy, XGBoostStrategy, generate_signal, get_strategy_for_run
from app.services.signal_engine.ml_strategy import MODEL_FEATURE_FIELDS


RULE_MEMBER_PARAMETERS = {
    "positive_sentiment_threshold": "0.5000",
    "negative_sentiment_threshold": "-0.5000",
    "positive_momentum_threshold": "0.0001",
    "negative_momentum_threshold": "-0.0001",
}


def _features(*, insufficient: bool = False) -> FeatureVector:
    return FeatureVector(
        symbol="XAUUSD",
        timestamp=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
        lookback_hours=24,
        sentiment_mean=Decimal("0.7000"),
        sentiment_count=2,
        event_count=2,
        geopolitical_event_count=1,
        price_momentum_4h=Decimal("0.0040"),
        latest_price=Decimal("2310.00000000"),
        has_insufficient_data=insufficient,
    )


def test_rule_strategy_matches_legacy_generate_signal_behavior() -> None:
    strategy_run = StrategyRun(
        strategy_name="sentiment_momentum_v1",
        version="1.0.0",
        parameters={
            "positive_sentiment_threshold": "0.5000",
            "negative_sentiment_threshold": "-0.5000",
            "positive_momentum_threshold": "0.0001",
            "negative_momentum_threshold": "-0.0001",
        },
    )

    generated = generate_signal(_features(), strategy_run)
    direct = RuleStrategy().generate_signal(_features(), strategy_run)

    assert get_strategy_for_run(strategy_run).__class__ is RuleStrategy
    assert generated == direct
    assert generated.direction == "BUY"
    assert generated.strength == Decimal("0.7400")
    assert generated.confidence == Decimal("0.8300")


def test_generate_signal_applies_enabled_confidence_calibration() -> None:
    strategy_run = StrategyRun(
        strategy_name="sentiment_momentum_v1",
        version="1.0.0",
        parameters={
            "confidence_calibration": {
                "enabled": True,
                "status": "fitted",
                "sample_count": 30,
                "min_samples": 30,
                "horizon_hours": 2,
                "return_threshold": "0.0030",
                "points": [
                    {
                        "raw_confidence_lower": "0.0000",
                        "raw_confidence_upper": "0.8300",
                        "calibrated_confidence": "0.7000",
                        "sample_count": 30,
                    }
                ],
            }
        },
    )

    decision = generate_signal(_features(), strategy_run)

    assert decision.direction == "BUY"
    assert decision.confidence == Decimal("0.7000")
    assert "confidence_calibrated" in decision.reasoning


def test_generate_signal_ignores_confidence_calibration_without_enough_samples() -> None:
    strategy_run = StrategyRun(
        strategy_name="sentiment_momentum_v1",
        version="1.0.0",
        parameters={
            "confidence_calibration": {
                "enabled": True,
                "status": "fitted",
                "sample_count": 2,
                "min_samples": 30,
                "horizon_hours": 2,
                "return_threshold": "0.0030",
                "points": [
                    {
                        "raw_confidence_lower": "0.0000",
                        "raw_confidence_upper": "1.0000",
                        "calibrated_confidence": "0.7000",
                        "sample_count": 2,
                    }
                ],
            }
        },
    )

    decision = generate_signal(_features(), strategy_run)

    assert decision.confidence == Decimal("0.8300")
    assert "confidence_calibrated" not in decision.reasoning


def test_ensemble_strategy_combines_member_votes_and_decimal_outputs() -> None:
    strategy_run = StrategyRun(
        strategy_name="ensemble_v1",
        version="0.1.0",
        parameters={
            "members": [
                {
                    "strategy_name": "sentiment_momentum_v1",
                    "version": "1.0.0",
                    "weight": "0.8000",
                    "parameters": dict(RULE_MEMBER_PARAMETERS),
                },
                {
                    "strategy_name": "xgboost_v1",
                    "version": "0.1.0",
                    "weight": "0.2000",
                    "parameters": {},
                },
            ]
        },
    )

    strategy = get_strategy_for_run(strategy_run)
    decision = generate_signal(_features(), strategy_run)

    assert strategy.__class__.__name__ == "EnsembleStrategy"
    assert decision.direction == "BUY"
    assert decision.strength == Decimal("0.5920")
    assert decision.confidence == Decimal("0.7140")
    assert isinstance(decision.strength, Decimal)
    assert isinstance(decision.confidence, Decimal)
    assert "ensemble_v1" in decision.reasoning


def test_strategy_registry_resolves_ensemble_from_strategy_type_parameter() -> None:
    strategy_run = StrategyRun(
        strategy_name="phase4_custom_ensemble",
        version="0.1.0",
        parameters={
            "strategy_type": "ensemble_v1",
            "members": [
                {
                    "strategy_name": "sentiment_momentum_v1",
                    "version": "1.0.0",
                    "weight": "1.0000",
                    "parameters": dict(RULE_MEMBER_PARAMETERS),
                }
            ],
        },
    )

    strategy = get_strategy_for_run(strategy_run)
    decision = generate_signal(_features(), strategy_run)

    assert strategy.__class__.__name__ == "EnsembleStrategy"
    assert decision.direction == "BUY"
    assert decision.strength == Decimal("0.7400")
    assert decision.confidence == Decimal("0.8300")


def test_ensemble_strategy_holds_when_all_members_hold() -> None:
    strategy_run = StrategyRun(
        strategy_name="ensemble_v1",
        version="0.1.0",
        parameters={
            "members": [
                {
                    "strategy_name": "xgboost_v1",
                    "version": "0.1.0",
                    "weight": "0.5000",
                    "parameters": {},
                },
                {
                    "strategy_name": "xgboost_v1",
                    "version": "0.1.0",
                    "weight": "0.5000",
                    "parameters": {},
                },
            ]
        },
    )

    decision = generate_signal(_features(), strategy_run)

    assert decision.direction == "HOLD"
    assert decision.strength == Decimal("0.0000")
    assert decision.confidence == Decimal("0.2500")
    assert "ensemble_v1" in decision.reasoning


def test_ensemble_strategy_ignores_unknown_member_strategies() -> None:
    strategy_run = StrategyRun(
        strategy_name="ensemble_v1",
        version="0.1.0",
        parameters={
            "members": [
                {
                    "strategy_name": "unknown_member_strategy",
                    "version": "0.1.0",
                    "weight": "1.0000",
                    "parameters": dict(RULE_MEMBER_PARAMETERS),
                }
            ]
        },
    )

    decision = generate_signal(_features(), strategy_run)

    assert decision.direction == "HOLD"
    assert decision.strength == Decimal("0.0000")
    assert decision.confidence == Decimal("0.2500")
    assert "ensemble_v1_no_valid_members" in decision.reasoning
    assert "unsupported_member=unknown_member_strategy" in decision.reasoning


def test_ensemble_strategy_ignores_invalid_member_weights() -> None:
    strategy_run = StrategyRun(
        strategy_name="ensemble_v1",
        version="0.1.0",
        parameters={
            "members": [
                {
                    "strategy_name": "sentiment_momentum_v1",
                    "version": "1.0.0",
                    "weight": "not-a-decimal",
                    "parameters": dict(RULE_MEMBER_PARAMETERS),
                },
                {
                    "strategy_name": "xgboost_v1",
                    "version": "0.1.0",
                    "weight": "1.0000",
                    "parameters": {},
                },
            ]
        },
    )

    decision = generate_signal(_features(), strategy_run)

    assert decision.direction == "HOLD"
    assert decision.strength == Decimal("0.0000")
    assert decision.confidence == Decimal("0.2500")
    assert "invalid_weight=not-a-decimal" in decision.reasoning


def test_xgboost_strategy_safely_holds_without_model_or_dependency() -> None:
    strategy_run = StrategyRun(
        strategy_name="xgboost_v1",
        version="0.1.0",
        parameters={},
    )

    strategy = get_strategy_for_run(strategy_run)
    decision = generate_signal(_features(), strategy_run)

    assert isinstance(strategy, XGBoostStrategy)
    assert decision.direction == "HOLD"
    assert decision.strength == Decimal("0.0000")
    assert decision.reasoning == "xgboost_model_unavailable"


def test_xgboost_strategy_loads_sklearn_artifact_and_generates_signal() -> None:
    from sklearn.linear_model import LogisticRegression

    artifact_path = Path(__file__).resolve().parent / "fixtures" / "phase1_sklearn_model_test.pkl"
    feature_count = len(MODEL_FEATURE_FIELDS)
    model = LogisticRegression(random_state=0)
    model.fit(
        [
            [0.0 for _field in MODEL_FEATURE_FIELDS],
            [1.0 for _field in MODEL_FEATURE_FIELDS],
        ],
        [0, 1],
    )
    with artifact_path.open("wb") as handle:
        pickle.dump(model, handle)

    try:
        strategy_run = StrategyRun(
            strategy_name="xgboost_v1",
            version="0.2.0",
            parameters={
                "model_artifact_uri": str(artifact_path),
                "model_loader": "sklearn_pickle",
                "buy_threshold": "0.5000",
                "sell_threshold": "0.4000",
            },
        )
        features = FeatureVector(
            symbol="XAUUSD",
            timestamp=datetime(2026, 4, 1, 6, 0, tzinfo=UTC),
            lookback_hours=24,
            sentiment_mean=Decimal("1.0000"),
            sentiment_count=1,
            event_count=1,
            geopolitical_event_count=1,
            price_momentum_4h=Decimal("1.0000"),
            latest_price=Decimal("2310.00000000"),
            has_insufficient_data=False,
            sentiment_std=Decimal("1.0000"),
            sentiment_velocity=Decimal("1.0000"),
            price_momentum_1h=Decimal("1.0000"),
            price_momentum_24h=Decimal("1.0000"),
            price_momentum_7d=Decimal("1.0000"),
            high_low_range=Decimal("1.0000"),
            rsi_14=Decimal("1.0000"),
            macd_line=Decimal("1.0000"),
            macd_signal=Decimal("1.0000"),
            macd_histogram=Decimal("1.0000"),
            bollinger_position=Decimal("1.0000"),
            bollinger_width=Decimal("1.0000"),
            atr_14=Decimal("1.0000"),
            ema_20_distance=Decimal("1.0000"),
            ema_50_distance=Decimal("1.0000"),
            sma_200_distance=Decimal("1.0000"),
            volume_ratio_20=Decimal("1.0000"),
            hour_of_day=1,
            day_of_week=1,
        )

        decision = XGBoostStrategy().generate_signal(features, strategy_run)
    finally:
        artifact_path.unlink(missing_ok=True)

    assert feature_count >= 24
    assert decision.direction == "BUY"
    assert decision.confidence > Decimal("0.5000")


def test_model_registry_registers_and_returns_active_model_version(db_session) -> None:
    registry = ModelRegistry(db_session)
    first = registry.register_model_version(
        model_name="xgboost_v1",
        version="0.1.0",
        model_type="xgboost",
        artifact_uri="models/xgboost-v0.1.json",
        feature_schema={"features": ["sentiment_mean"]},
        metrics={"auc": "0.5100"},
        status="validated",
        is_active=True,
        trained_at=datetime(2026, 4, 1, 1, 0, tzinfo=UTC),
    )
    second = registry.register_model_version(
        model_name="xgboost_v1",
        version="0.2.0",
        model_type="xgboost",
        artifact_uri="models/xgboost-v0.2.json",
        feature_schema={"features": ["sentiment_mean", "price_momentum_4h"]},
        metrics={"auc": "0.5200"},
        status="validated",
        is_active=True,
        trained_at=datetime(2026, 4, 2, 1, 0, tzinfo=UTC),
    )
    db_session.commit()

    db_session.refresh(first)
    db_session.refresh(second)
    active = registry.get_active_model(model_name="xgboost_v1", model_type="xgboost")

    assert active is not None
    assert active.id == second.id
    assert first.is_active is False
    assert second.is_active is True
    assert isinstance(second, ModelVersion)
    assert second.metrics["auc"] == "0.5200"
    assert second.trained_at.tzinfo == UTC


def test_generate_signal_resolves_active_xgboost_model_with_session(db_session, monkeypatch) -> None:
    registry = ModelRegistry(db_session)
    active_model = registry.register_model_version(
        model_name="xgboost_v1",
        version="0.2.0",
        model_type="xgboost",
        artifact_uri="models/active-xgboost.json",
        feature_schema={"features": ["sentiment_mean", "price_momentum_4h"]},
        metrics={"auc": "0.5200"},
        status="validated",
        is_active=True,
        trained_at=datetime(2026, 4, 2, 1, 0, tzinfo=UTC),
    )
    db_session.commit()

    loaded_artifacts: list[str] = []

    def fake_load_model(self, artifact_uri: str):
        loaded_artifacts.append(artifact_uri)
        return object()

    def fake_predict(self, model, features: FeatureVector) -> Decimal:
        return Decimal("0.6200")

    monkeypatch.setattr(XGBoostStrategy, "_load_model", fake_load_model)
    monkeypatch.setattr(XGBoostStrategy, "_predict", fake_predict)

    strategy_run = StrategyRun(
        strategy_name="xgboost_v1",
        version="0.1.0",
        parameters={},
    )

    decision = generate_signal(_features(), strategy_run, session=db_session)

    assert active_model.artifact_uri == "models/active-xgboost.json"
    assert loaded_artifacts == ["models/active-xgboost.json"]
    assert decision.direction == "BUY"
    assert decision.confidence == Decimal("0.6200")
    assert decision.reasoning == "buy from xgboost_v1 probability=0.6200"
