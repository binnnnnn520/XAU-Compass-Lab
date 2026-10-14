from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.models import MarketBar, Signal, StrategyRun
from app.services.calibration import (
    CalibrationSample,
    build_calibration_samples,
    build_reliability_report,
    fit_confidence_calibrator,
)


def _market_bar(hour: int, close: str) -> MarketBar:
    close_price = Decimal(close)
    return MarketBar(
        symbol="XAUUSD",
        timeframe="1h",
        bar_time=datetime(2026, 4, 1, hour, 0, tzinfo=UTC),
        open=close_price,
        high=close_price + Decimal("1.00000000"),
        low=close_price - Decimal("1.00000000"),
        close=close_price,
        volume=Decimal("10.00000000"),
    )


def _signal(
    strategy: StrategyRun,
    *,
    hour: int,
    direction: str,
    confidence: str,
    price: str = "100.00000000",
) -> Signal:
    return Signal(
        strategy_run=strategy,
        symbol="XAUUSD",
        signal_time=datetime(2026, 4, 1, hour, 0, tzinfo=UTC),
        direction=direction,
        strength=Decimal("0.5000"),
        confidence=Decimal(confidence),
        price_at_signal=Decimal(price),
        features_used={"fixture": True},
        reasoning="fixture",
        source_type="backtest",
    )


def _sample(raw_confidence: str, *, is_correct: bool) -> CalibrationSample:
    return CalibrationSample(
        signal_id=uuid4(),
        signal_time=datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
        direction="BUY",
        raw_confidence=Decimal(raw_confidence),
        price_at_signal=Decimal("100.00000000"),
        future_price_time=datetime(2026, 4, 1, 2, 0, tzinfo=UTC),
        future_price=Decimal("101.00000000"),
        future_return=Decimal("0.0100"),
        label="BUY" if is_correct else "SELL",
        is_correct=is_correct,
        horizon_hours=2,
        return_threshold=Decimal("0.0030"),
    )


def test_build_calibration_samples_uses_fixed_future_horizon_without_mutating_signals(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="ensemble_v1",
        version="0.1.0",
        parameters={},
        is_active=True,
    )
    db_session.add(strategy)
    db_session.add_all(
        [
            _signal(strategy, hour=0, direction="BUY", confidence="0.8000"),
            _signal(strategy, hour=3, direction="BUY", confidence="0.6000"),
            _signal(strategy, hour=6, direction="HOLD", confidence="0.4000"),
            _market_bar(1, "105.00000000"),
            _market_bar(2, "101.00000000"),
            _market_bar(5, "99.00000000"),
            _market_bar(8, "100.10000000"),
        ]
    )
    db_session.commit()

    samples = build_calibration_samples(
        db_session,
        horizon_hours=2,
        return_threshold=Decimal("0.0030"),
        symbol="XAUUSD",
        timeframe="1h",
    )

    persisted_signals = db_session.query(Signal).count()

    assert persisted_signals == 3
    assert [sample.label for sample in samples] == ["BUY", "SELL", "HOLD"]
    assert [sample.is_correct for sample in samples] == [True, False, True]
    assert samples[0].future_price_time == datetime(2026, 4, 1, 2, 0, tzinfo=UTC)
    assert samples[0].future_return == Decimal("0.0100")
    assert samples[1].future_return == Decimal("-0.0100")
    assert samples[2].future_return == Decimal("0.0010")
    assert all(sample.signal_time.tzinfo == UTC for sample in samples)
    assert all(isinstance(sample.raw_confidence, Decimal) for sample in samples)


def test_build_reliability_report_outputs_brier_accuracy_and_confidence_bins(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="ensemble_v1",
        version="0.1.0",
        parameters={},
        is_active=True,
    )
    db_session.add(strategy)
    db_session.add_all(
        [
            _signal(strategy, hour=0, direction="BUY", confidence="0.8000"),
            _signal(strategy, hour=3, direction="BUY", confidence="0.6000"),
            _signal(strategy, hour=6, direction="HOLD", confidence="0.4000"),
            _market_bar(2, "101.00000000"),
            _market_bar(5, "99.00000000"),
            _market_bar(8, "100.10000000"),
        ]
    )
    db_session.commit()

    samples = build_calibration_samples(
        db_session,
        horizon_hours=2,
        return_threshold=Decimal("0.0030"),
        symbol="XAUUSD",
        timeframe="1h",
    )
    report = build_reliability_report(samples, bin_count=5)

    assert report.sample_count == 3
    assert report.horizon_hours == 2
    assert report.return_threshold == Decimal("0.0030")
    assert report.accuracy == Decimal("0.6667")
    assert report.brier_score == Decimal("0.2533")
    assert report.coverage == Decimal("1.0000")
    assert [bin.sample_count for bin in report.bins] == [1, 1, 1]
    assert {bin.bin_lower for bin in report.bins} == {
        Decimal("0.4000"),
        Decimal("0.6000"),
        Decimal("0.8000"),
    }


def test_fit_confidence_calibrator_requires_minimum_runtime_labels() -> None:
    result = fit_confidence_calibrator(
        [_sample("0.5000", is_correct=True)],
        min_samples=2,
    )

    assert result.status == "insufficient_samples"
    assert result.sample_count == 1
    assert result.min_samples == 2
    assert result.model is None
    assert result.report.sample_count == 1


def test_fit_confidence_calibrator_builds_monotonic_decimal_model() -> None:
    result = fit_confidence_calibrator(
        [
            _sample("0.2000", is_correct=True),
            _sample("0.2000", is_correct=False),
            _sample("0.5000", is_correct=False),
            _sample("0.5000", is_correct=False),
            _sample("0.8000", is_correct=True),
            _sample("0.8000", is_correct=True),
        ],
        min_samples=6,
    )

    assert result.status == "fitted"
    assert result.sample_count == 6
    assert result.model is not None
    assert [point.calibrated_confidence for point in result.model.points] == [
        Decimal("0.2500"),
        Decimal("1.0000"),
    ]
    assert result.model.calibrate(Decimal("0.2000")) == Decimal("0.2500")
    assert result.model.calibrate(Decimal("0.5000")) == Decimal("0.2500")
    assert result.model.calibrate(Decimal("0.8000")) == Decimal("1.0000")
    assert all(isinstance(point.calibrated_confidence, Decimal) for point in result.model.points)
