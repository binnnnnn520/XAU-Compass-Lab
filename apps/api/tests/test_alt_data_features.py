from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import MarketBar
from app.services.alt_data import CotReport, DxyIndexBar, EtfFlowRecord, build_alternative_data_snapshot
from app.services.feature_engine import compute_features


def _market_bar(hours: int, close: str) -> MarketBar:
    price = Decimal(close)
    return MarketBar(
        symbol="XAUUSD",
        timeframe="1h",
        bar_time=datetime(2026, 4, 1, hours, 0, tzinfo=UTC),
        open=price,
        high=price + Decimal("1.00000000"),
        low=price - Decimal("1.00000000"),
        close=price,
        volume=Decimal("10.00000000"),
    )


def test_build_alternative_data_snapshot_uses_only_records_available_before_timestamp() -> None:
    timestamp = datetime(2026, 4, 8, 12, 0, tzinfo=UTC)
    snapshot = build_alternative_data_snapshot(
        timestamp=timestamp,
        cot_reports=[
            CotReport(
                report_time=datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
                created_at=datetime(2026, 4, 2, 0, 0, tzinfo=UTC),
                managed_money_long=Decimal("120.0000"),
                managed_money_short=Decimal("80.0000"),
                open_interest=Decimal("200.0000"),
            ),
            CotReport(
                report_time=timestamp,
                created_at=datetime(2026, 4, 8, 11, 0, tzinfo=UTC),
                managed_money_long=Decimal("999.0000"),
                managed_money_short=Decimal("1.0000"),
                open_interest=Decimal("1000.0000"),
            ),
        ],
        etf_flows=[
            EtfFlowRecord(
                as_of=datetime(2026, 4, 6, 0, 0, tzinfo=UTC),
                created_at=datetime(2026, 4, 6, 1, 0, tzinfo=UTC),
                fund="GLD",
                flow_ounces=Decimal("10.0000"),
                holdings_ounces=Decimal("1000.0000"),
            ),
            EtfFlowRecord(
                as_of=datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
                created_at=datetime(2026, 4, 7, 1, 0, tzinfo=UTC),
                fund="IAU",
                flow_ounces=Decimal("-2.5000"),
                holdings_ounces=Decimal("400.0000"),
            ),
            EtfFlowRecord(
                as_of=datetime(2026, 4, 3, 0, 0, tzinfo=UTC),
                created_at=datetime(2026, 4, 9, 1, 0, tzinfo=UTC),
                fund="GLD",
                flow_ounces=Decimal("500.0000"),
                holdings_ounces=Decimal("9999.0000"),
            ),
        ],
        dxy_bars=[
            DxyIndexBar(
                bar_time=datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
                created_at=datetime(2026, 4, 7, 0, 1, tzinfo=UTC),
                close=Decimal("100.0000"),
            ),
            DxyIndexBar(
                bar_time=datetime(2026, 4, 8, 0, 0, tzinfo=UTC),
                created_at=datetime(2026, 4, 8, 0, 1, tzinfo=UTC),
                close=Decimal("101.0000"),
            ),
            DxyIndexBar(
                bar_time=timestamp,
                created_at=datetime(2026, 4, 8, 12, 0, tzinfo=UTC),
                close=Decimal("120.0000"),
            ),
        ],
    )

    assert snapshot.cot_net_position_ratio == Decimal("0.2000")
    assert snapshot.etf_flow_ounces_5d == Decimal("7.5000")
    assert snapshot.etf_holdings_ounces == Decimal("1400.0000")
    assert snapshot.dxy_momentum_1d == Decimal("0.0100")


def test_compute_features_includes_alternative_data_snapshot(db_session) -> None:
    timestamp = datetime(2026, 4, 1, 6, 0, tzinfo=UTC)
    snapshot = build_alternative_data_snapshot(
        timestamp=timestamp,
        cot_reports=[
            CotReport(
                report_time=timestamp - timedelta(days=1),
                created_at=timestamp - timedelta(hours=23),
                managed_money_long=Decimal("120.0000"),
                managed_money_short=Decimal("80.0000"),
                open_interest=Decimal("200.0000"),
            )
        ],
        etf_flows=[
            EtfFlowRecord(
                as_of=timestamp - timedelta(days=1),
                created_at=timestamp - timedelta(hours=23),
                fund="GLD",
                flow_ounces=Decimal("10.0000"),
                holdings_ounces=Decimal("1000.0000"),
            )
        ],
        dxy_bars=[
            DxyIndexBar(
                bar_time=timestamp - timedelta(days=1),
                created_at=timestamp - timedelta(days=1),
                close=Decimal("100.0000"),
            ),
            DxyIndexBar(
                bar_time=timestamp - timedelta(hours=1),
                created_at=timestamp - timedelta(minutes=30),
                close=Decimal("101.0000"),
            ),
        ],
    )
    db_session.add_all(
        [
            _market_bar(1, "2300.00000000"),
            _market_bar(2, "2302.00000000"),
            _market_bar(3, "2304.00000000"),
            _market_bar(4, "2306.00000000"),
            _market_bar(5, "2308.00000000"),
        ]
    )
    db_session.commit()

    features = compute_features(db_session, "XAUUSD", timestamp, 24, alternative_data=snapshot)

    assert features.cot_net_position_ratio == Decimal("0.2000")
    assert features.etf_flow_ounces_5d == Decimal("10.0000")
    assert features.etf_holdings_ounces == Decimal("1000.0000")
    assert features.dxy_momentum_1d == Decimal("0.0100")
    assert features.snapshot()["cot_net_position_ratio"] == "0.2000"
