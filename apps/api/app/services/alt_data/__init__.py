from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.services.alt_data.cot_data import CotReport, cot_net_position_ratio
from app.services.alt_data.dxy_index import DxyIndexBar, dxy_momentum_1d
from app.services.alt_data.etf_flows import (
    EtfFlowRecord,
    etf_flow_ounces,
    latest_etf_holdings_ounces,
)


@dataclass(frozen=True)
class AlternativeDataSnapshot:
    cot_net_position_ratio: Decimal = Decimal("0.0000")
    etf_flow_ounces_5d: Decimal = Decimal("0.0000")
    etf_holdings_ounces: Decimal = Decimal("0.0000")
    dxy_momentum_1d: Decimal = Decimal("0.0000")


def build_alternative_data_snapshot(
    *,
    timestamp: datetime,
    cot_reports: list[CotReport] | None = None,
    etf_flows: list[EtfFlowRecord] | None = None,
    dxy_bars: list[DxyIndexBar] | None = None,
) -> AlternativeDataSnapshot:
    cot_reports = cot_reports or []
    etf_flows = etf_flows or []
    dxy_bars = dxy_bars or []
    return AlternativeDataSnapshot(
        cot_net_position_ratio=cot_net_position_ratio(cot_reports, timestamp),
        etf_flow_ounces_5d=etf_flow_ounces(etf_flows, timestamp, lookback_days=5),
        etf_holdings_ounces=latest_etf_holdings_ounces(etf_flows, timestamp),
        dxy_momentum_1d=dxy_momentum_1d(dxy_bars, timestamp),
    )


__all__ = [
    "AlternativeDataSnapshot",
    "CotReport",
    "DxyIndexBar",
    "EtfFlowRecord",
    "build_alternative_data_snapshot",
]
