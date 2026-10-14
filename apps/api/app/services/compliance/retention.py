from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


RETENTION_YEARS = 5


@dataclass(frozen=True)
class Phase5RetentionRule:
    table_name: str
    timestamp_column: str
    min_retention_years: int
    append_only: bool
    protected_actions: tuple[str, ...]


@dataclass(frozen=True)
class Phase5RetentionPolicy:
    retention_years: int
    rules: tuple[Phase5RetentionRule, ...]


@dataclass(frozen=True)
class Phase5RetentionDecision:
    allowed: bool
    reason: str | None
    retain_until: datetime | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("retention datetimes must be UTC-aware")
    return value.astimezone(UTC)


def _add_years(value: datetime, years: int) -> datetime:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, month=2, day=28)


def build_phase5_retention_policy() -> Phase5RetentionPolicy:
    return Phase5RetentionPolicy(
        retention_years=RETENTION_YEARS,
        rules=(
            Phase5RetentionRule(
                table_name="audit_logs",
                timestamp_column="created_at",
                min_retention_years=RETENTION_YEARS,
                append_only=True,
                protected_actions=("update", "delete"),
            ),
            Phase5RetentionRule(
                table_name="risk_events",
                timestamp_column="created_at",
                min_retention_years=RETENTION_YEARS,
                append_only=False,
                protected_actions=("delete",),
            ),
            Phase5RetentionRule(
                table_name="paper_orders",
                timestamp_column="created_at",
                min_retention_years=RETENTION_YEARS,
                append_only=False,
                protected_actions=("delete",),
            ),
            Phase5RetentionRule(
                table_name="paper_positions",
                timestamp_column="created_at",
                min_retention_years=RETENTION_YEARS,
                append_only=False,
                protected_actions=("delete",),
            ),
            Phase5RetentionRule(
                table_name="live_parallel_observations",
                timestamp_column="created_at",
                min_retention_years=RETENTION_YEARS,
                append_only=False,
                protected_actions=("delete",),
            ),
        ),
    )


def evaluate_retention_action(
    *,
    table_name: str,
    action: str,
    record_timestamp: datetime,
    as_of: datetime,
) -> Phase5RetentionDecision:
    normalized_action = action.lower()
    record_timestamp_utc = _as_utc(record_timestamp)
    as_of_utc = _as_utc(as_of)
    rules = {rule.table_name: rule for rule in build_phase5_retention_policy().rules}
    rule = rules.get(table_name)
    if rule is None:
        raise ValueError(f"unknown Phase 5 retention table: {table_name}")

    retain_until = _add_years(record_timestamp_utc, rule.min_retention_years)
    if rule.append_only and normalized_action in rule.protected_actions:
        return Phase5RetentionDecision(
            allowed=False,
            reason="append_only_table",
            retain_until=retain_until,
        )
    if normalized_action == "delete" and as_of_utc < retain_until:
        return Phase5RetentionDecision(
            allowed=False,
            reason="minimum_retention_window_active",
            retain_until=retain_until,
        )
    return Phase5RetentionDecision(allowed=True, reason=None, retain_until=retain_until)
