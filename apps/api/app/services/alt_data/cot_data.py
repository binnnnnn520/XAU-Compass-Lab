from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP


ALT_DATA_QUANTIZER = Decimal("0.0001")


@dataclass(frozen=True)
class CotReport:
    report_time: datetime
    created_at: datetime
    managed_money_long: Decimal
    managed_money_short: Decimal
    open_interest: Decimal


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("alternative data datetimes must be UTC-aware")
    return value.astimezone(UTC)


def quantize_alt_data(value: Decimal) -> Decimal:
    return value.quantize(ALT_DATA_QUANTIZER, rounding=ROUND_HALF_UP)


def latest_available_cot_report(reports: list[CotReport], timestamp: datetime) -> CotReport | None:
    normalized_timestamp = _as_utc(timestamp)
    available = [
        report
        for report in reports
        if _as_utc(report.report_time) < normalized_timestamp
        and _as_utc(report.created_at) < normalized_timestamp
    ]
    if not available:
        return None
    return max(available, key=lambda report: (_as_utc(report.report_time), _as_utc(report.created_at)))


def cot_net_position_ratio(reports: list[CotReport], timestamp: datetime) -> Decimal:
    report = latest_available_cot_report(reports, timestamp)
    if report is None or report.open_interest == Decimal("0"):
        return Decimal("0.0000")
    return quantize_alt_data(
        (report.managed_money_long - report.managed_money_short) / report.open_interest
    )
