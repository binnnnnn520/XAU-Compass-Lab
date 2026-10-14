from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModelVersion, StrategyRun
from app.services.signal_engine.ensemble_strategy import DEFAULT_ENSEMBLE_STRATEGY_NAME, EnsembleStrategy
from app.services.signal_engine.ml_strategy import DEFAULT_XGBOOST_STRATEGY_NAME, XGBoostStrategy
from app.services.signal_engine.rule_strategy import DEFAULT_STRATEGY_NAME, RuleStrategy
from app.services.signal_engine.strategy_interface import StrategyInterface


XGBOOST_STRATEGY_NAMES = {DEFAULT_XGBOOST_STRATEGY_NAME, "xgboost_gold_v1"}


class ModelRegistry:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register_model_version(
        self,
        *,
        model_name: str,
        version: str,
        model_type: str,
        artifact_uri: str | None = None,
        feature_schema: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        status: str = "candidate",
        is_active: bool = False,
        trained_at: datetime | None = None,
    ) -> ModelVersion:
        if is_active:
            self.deactivate_model_versions(model_name=model_name, model_type=model_type)

        model_version = ModelVersion(
            model_name=model_name,
            version=version,
            model_type=model_type,
            artifact_uri=artifact_uri,
            feature_schema=feature_schema or {},
            metrics=metrics or {},
            status=status,
            is_active=is_active,
            trained_at=trained_at,
        )
        self.session.add(model_version)
        self.session.flush()
        return model_version

    def deactivate_model_versions(self, *, model_name: str, model_type: str | None = None) -> int:
        query = select(ModelVersion).where(ModelVersion.model_name == model_name, ModelVersion.is_active.is_(True))
        if model_type is not None:
            query = query.where(ModelVersion.model_type == model_type)

        rows = self.session.execute(query).scalars().all()
        for row in rows:
            row.is_active = False
            self.session.add(row)
        self.session.flush()
        return len(rows)

    def get_active_model(self, *, model_name: str, model_type: str | None = None) -> ModelVersion | None:
        query = (
            select(ModelVersion)
            .where(ModelVersion.model_name == model_name, ModelVersion.is_active.is_(True))
            .order_by(ModelVersion.created_at.desc())
        )
        if model_type is not None:
            query = query.where(ModelVersion.model_type == model_type)
        return self.session.execute(query).scalars().first()

    def get_model_version(self, model_version_id: uuid.UUID) -> ModelVersion | None:
        return self.session.get(ModelVersion, model_version_id)


def get_strategy_for_run(strategy_run: StrategyRun, session: Session | None = None) -> StrategyInterface:
    parameters = strategy_run.parameters or {}
    strategy_type = str(parameters.get("strategy_type") or strategy_run.strategy_name)

    if strategy_type == DEFAULT_ENSEMBLE_STRATEGY_NAME or strategy_run.strategy_name == DEFAULT_ENSEMBLE_STRATEGY_NAME:
        return EnsembleStrategy(session=session)

    if strategy_type in XGBOOST_STRATEGY_NAMES or strategy_run.strategy_name in XGBOOST_STRATEGY_NAMES:
        model_version = _resolve_model_version(strategy_run, session)
        return XGBoostStrategy(model_version=model_version)

    if strategy_run.strategy_name == DEFAULT_STRATEGY_NAME or strategy_type == DEFAULT_STRATEGY_NAME:
        return RuleStrategy()

    return RuleStrategy()


def _resolve_model_version(strategy_run: StrategyRun, session: Session | None) -> ModelVersion | None:
    if session is None:
        return None

    parameters = strategy_run.parameters or {}
    raw_model_version_id = parameters.get("model_version_id")
    if raw_model_version_id:
        try:
            return session.get(ModelVersion, uuid.UUID(str(raw_model_version_id)))
        except ValueError:
            return None

    model_name = str(parameters.get("model_name") or strategy_run.strategy_name)
    model_type = str(parameters.get("model_type") or "xgboost")
    return ModelRegistry(session).get_active_model(model_name=model_name, model_type=model_type)
