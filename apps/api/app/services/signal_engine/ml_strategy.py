from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import pickle
from pathlib import Path
from typing import Any

from app.models import ModelVersion, StrategyRun
from app.services.feature_engine import FeatureVector
from app.services.signal_engine.strategy_interface import SignalDecision


SIGNAL_QUANTIZER = Decimal("0.0001")
DEFAULT_XGBOOST_STRATEGY_NAME = "xgboost_v1"
MODEL_FEATURE_FIELDS = (
    "sentiment_mean",
    "sentiment_std",
    "sentiment_velocity",
    "sentiment_count",
    "event_count",
    "geopolitical_event_count",
    "price_momentum_1h",
    "price_momentum_4h",
    "price_momentum_24h",
    "price_momentum_7d",
    "high_low_range",
    "rsi_14",
    "macd_line",
    "macd_signal",
    "macd_histogram",
    "bollinger_position",
    "bollinger_width",
    "atr_14",
    "ema_20_distance",
    "ema_50_distance",
    "sma_200_distance",
    "volume_ratio_20",
    "hour_of_day",
    "day_of_week",
)


def _hold(reason: str, confidence: Decimal = Decimal("0.2500")) -> SignalDecision:
    return SignalDecision(
        direction="HOLD",
        strength=Decimal("0.0000"),
        confidence=confidence.quantize(SIGNAL_QUANTIZER, rounding=ROUND_HALF_UP),
        reasoning=reason,
    )


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def _feature_value(features: FeatureVector, field_name: str) -> float:
    value = getattr(features, field_name)
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return 0.0
    return float(value)


class XGBoostStrategy:
    strategy_name = DEFAULT_XGBOOST_STRATEGY_NAME

    def __init__(self, model_version: ModelVersion | None = None) -> None:
        self.model_version = model_version

    def generate_signal(self, features: FeatureVector, strategy_run: StrategyRun) -> SignalDecision:
        if features.has_insufficient_data:
            return _hold("insufficient_data")

        parameters = strategy_run.parameters or {}
        artifact_uri = str(
            parameters.get("model_artifact_uri")
            or (self.model_version.artifact_uri if self.model_version is not None else "")
            or ""
        )
        if not artifact_uri:
            return _hold("xgboost_model_unavailable")

        model_loader = str(parameters.get("model_loader") or "xgboost")
        model = self._load_model_for_run(artifact_uri, model_loader=model_loader)
        if model is None:
            return _hold("xgboost_model_unavailable")

        prediction = self._predict_for_run(model, features, model_loader=model_loader)
        if prediction is None:
            return _hold("xgboost_prediction_unavailable")

        buy_threshold = Decimal(str(parameters.get("buy_threshold", "0.5500")))
        sell_threshold = Decimal(str(parameters.get("sell_threshold", "0.4500")))
        confidence = _clamp(prediction, Decimal("0.0100"), Decimal("0.9900"))

        if prediction >= buy_threshold:
            direction = "BUY"
            strength = _clamp((prediction - buy_threshold) / max(Decimal("0.0001"), Decimal("1") - buy_threshold), Decimal("0.0000"), Decimal("1.0000"))
        elif prediction <= sell_threshold:
            direction = "SELL"
            strength = _clamp((sell_threshold - prediction) / max(Decimal("0.0001"), sell_threshold), Decimal("0.0000"), Decimal("1.0000"))
        else:
            return _hold("xgboost_thresholds_not_met", confidence=confidence)

        return SignalDecision(
            direction=direction,
            strength=strength.quantize(SIGNAL_QUANTIZER, rounding=ROUND_HALF_UP),
            confidence=confidence.quantize(SIGNAL_QUANTIZER, rounding=ROUND_HALF_UP),
            reasoning=f"{direction.lower()} from xgboost_v1 probability={confidence}",
        )

    def _load_model(self, artifact_uri: str, *, model_loader: str = "xgboost") -> Any | None:
        artifact_path = Path(artifact_uri)
        if not artifact_path.exists() or not artifact_path.is_file():
            return None

        if model_loader == "sklearn_pickle":
            try:
                with artifact_path.open("rb") as handle:
                    return pickle.load(handle)
            except Exception:
                return None

        try:
            import xgboost as xgb  # type: ignore[import-not-found]
        except Exception:
            return None

        try:
            model = xgb.Booster()
            model.load_model(str(artifact_path))
            return model
        except Exception:
            return None

    def _load_model_for_run(self, artifact_uri: str, *, model_loader: str) -> Any | None:
        try:
            return self._load_model(artifact_uri, model_loader=model_loader)
        except TypeError as exc:
            if "model_loader" not in str(exc):
                raise
            return self._load_model(artifact_uri)

    def _predict(self, model: Any, features: FeatureVector, *, model_loader: str = "xgboost") -> Decimal | None:
        row = [[_feature_value(features, field_name) for field_name in MODEL_FEATURE_FIELDS]]
        if model_loader == "sklearn_pickle":
            return self._predict_sklearn(model, row)

        try:
            import xgboost as xgb  # type: ignore[import-not-found]

            prediction = model.predict(xgb.DMatrix(row))[0]
            return Decimal(str(prediction))
        except Exception:
            return None

    def _predict_for_run(self, model: Any, features: FeatureVector, *, model_loader: str) -> Decimal | None:
        try:
            return self._predict(model, features, model_loader=model_loader)
        except TypeError as exc:
            if "model_loader" not in str(exc):
                raise
            return self._predict(model, features)

    def _predict_sklearn(self, model: Any, row: list[list[float]]) -> Decimal | None:
        try:
            if hasattr(model, "predict_proba"):
                probabilities = model.predict_proba(row)
                first_row = probabilities[0]
                if len(first_row) < 2:
                    return Decimal(str(first_row[0]))
                return Decimal(str(first_row[1]))
            prediction = model.predict(row)[0]
            return Decimal(str(prediction))
        except Exception:
            return None
