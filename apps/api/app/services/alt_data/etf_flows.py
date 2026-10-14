from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.alt_data.cot_data import quantize_alt_data


@dataclass(frozen=True)
class EtfFlowRecord:
    as_of: datetime
    created_at: datetime
    fund: str
    flow_ounces: Decimal
    holdings_ounces: Decimal


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("alternative data datetimes must be UTC-aware")
    return value.astimezone(UTC)


def available_etf_flows(records: list[EtfFlowRecord], timestamp: datetime) -> list[EtfFlowRecord]:
    normalized_timestamp = _as_utc(timestamp)
    return [
        record
        for record in records
        if _as_utc(record.as_of) < normalized_timestamp
        and _as_utc(record.created_at) < normalized_timestamp
    ]


def etf_flow_ounces(records: list[EtfFlowRecord], timestamp: datetime, *, lookback_days: int = 5) -> Decimal:
    normalized_timestamp = _as_utc(timestamp)
    window_start = normalized_timestamp - timedelta(days=lookback_days)
    available = [
        record
        for record in available_etf_flows(records, normalized_timestamp)
        if _as_utc(record.as_of) >= window_start
    ]
    return quantize_alt_data(sum((record.flow_ounces for record in available), Decimal("0.0000")))


def latest_etf_holdings_ounces(records: list[EtfFlowRecord], timestamp: datetime) -> Decimal:
    holdings_by_fund: dict[str, EtfFlowRecord] = {}
    for record in available_etf_flows(records, timestamp):
        previous = holdings_by_fund.get(record.fund)
        if previous is None or (_as_utc(record.as_of), _as_utc(record.created_at)) > (
            _as_utc(previous.as_of),
            _as_utc(previous.created_at),
        ):
            holdings_by_fund[record.fund] = record
    return quantize_alt_data(
        sum((record.holdings_ounces for record in holdings_by_fund.values()), Decimal("0.0000"))
    )
