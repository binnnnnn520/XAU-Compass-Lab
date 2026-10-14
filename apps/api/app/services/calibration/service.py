from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarketBar, Signal


DECIMAL_QUANTIZER = Decimal("0.0001")
SUPPORTED_LABELS = {"BUY", "SELL", "HOLD"}


@dataclass(frozen=True)
class CalibrationSample:
    signal_id: UUID
    signal_time: datetime
    direction: str
    raw_confidence: Decimal
    price_at_signal: Decimal
    future_price_time: datetime
    future_price: Decimal
    future_return: Decimal
    label: str
    is_correct: bool
    horizon_hours: int
    return_threshold: Decimal


@dataclass(frozen=True)
class ReliabilityBin:
    bin_lower: Decimal
    bin_upper: Decimal
    sample_count: int
    average_confidence: Decimal
    accuracy: Decimal


@dataclass(frozen=True)
class CalibrationReport:
    sample_count: int
    horizon_hours: int
    return_threshold: Decimal
    accuracy: Decimal
    brier_score: Decimal
    coverage: Decimal
    bins: list[ReliabilityBin]


@dataclass(frozen=True)
class IsotonicCalibrationPoint:
    raw_confidence_lower: Decimal
    raw_confidence_upper: Decimal
    calibrated_confidence: Decimal
    sample_count: int


@dataclass(frozen=True)
class IsotonicConfidenceCalibrator:
    points: list[IsotonicCalibrationPoint]
    sample_count: int
    horizon_hours: int
    return_threshold: Decimal

    def calibrate(self, raw_confidence: Decimal) -> Decimal:
        if not self.points:
            return _quantize(_clamp_probability(raw_confidence))

        confidence = _quantize(_clamp_probability(raw_confidence))
        for point in self.points:
            if confidence <= point.raw_confidence_upper:
                return point.calibrated_confidence
        return self.points[-1].calibrated_confidence


@dataclass(frozen=True)
class CalibrationFitResult:
    status: str
    sample_count: int
    min_samples: int
    report: CalibrationReport
    model: IsotonicConfidenceCalibrator | None


@dataclass
class _IsotonicBlock:
    raw_confidence_lower: Decimal
    raw_confidence_upper: Decimal
    correct_total: Decimal
    sample_count: int

    @property
    def average(self) -> Decimal:
        return self.correct_total / Decimal(self.sample_count)

    def merge(self, other: "_IsotonicBlock") -> "_IsotonicBlock":
        return _IsotonicBlock(
            raw_confidence_lower=self.raw_confidence_lower,
            raw_confidence_upper=other.raw_confidence_upper,
            correct_total=self.correct_total + other.correct_total,
            sample_count=self.sample_count + other.sample_count,
        )


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(DECIMAL_QUANTIZER, rounding=ROUND_HALF_UP)


def _clamp_probability(value: Decimal) -> Decimal:
    return min(Decimal("1.0000"), max(Decimal("0.0000"), value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("calibration datetimes must be UTC-aware")
    return value.astimezone(UTC)


def _future_label(future_return: Decimal, threshold: Decimal) -> str:
    if future_return > threshold:
        return "BUY"
    if future_return < -threshold:
        return "SELL"
    return "HOLD"


def build_calibration_samples(
    session: Session,
    *,
    horizon_hours: int,
    return_threshold: Decimal,
    symbol: str = "XAUUSD",
    timeframe: str = "1h",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[CalibrationSample]:
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    if return_threshold < Decimal("0"):
        raise ValueError("return_threshold must be non-negative")

    query = (
        select(Signal)
        .where(
            Signal.symbol == symbol,
            Signal.price_at_signal.is_not(None),
        )
        .order_by(Signal.signal_time.asc(), Signal.id.asc())
    )
    if start_time is not None:
        query = query.where(Signal.signal_time >= _as_utc(start_time))
    if end_time is not None:
        query = query.where(Signal.signal_time <= _as_utc(end_time))

    samples: list[CalibrationSample] = []
    for signal in session.execute(query).scalars().all():
        signal_time = _as_utc(signal.signal_time)
        direction = signal.direction.upper()
        if direction not in SUPPORTED_LABELS or signal.price_at_signal is None:
            continue
        if signal.price_at_signal <= Decimal("0"):
            continue

        target_time = signal_time + timedelta(hours=horizon_hours)
        future_bar = session.execute(
            select(MarketBar)
            .where(
                MarketBar.symbol == symbol,
                MarketBar.timeframe == timeframe,
                MarketBar.bar_time >= target_time,
            )
            .order_by(MarketBar.bar_time.asc())
            .limit(1)
        ).scalars().first()
        if future_bar is None:
            continue

        future_return = _quantize(
            (future_bar.close - signal.price_at_signal) / signal.price_at_signal,
        )
        label = _future_label(future_return, return_threshold)
        samples.append(
            CalibrationSample(
                signal_id=signal.id,
                signal_time=signal_time,
                direction=direction,
                raw_confidence=_quantize(signal.confidence),
                price_at_signal=signal.price_at_signal,
                future_price_time=_as_utc(future_bar.bar_time),
                future_price=future_bar.close,
                future_return=future_return,
                label=label,
                is_correct=direction == label,
                horizon_hours=horizon_hours,
                return_threshold=_quantize(return_threshold),
            )
        )

    return samples


def build_reliability_report(samples: list[CalibrationSample], *, bin_count: int = 10) -> CalibrationReport:
    if bin_count <= 0:
        raise ValueError("bin_count must be positive")

    sample_count = len(samples)
    horizon_hours = samples[0].horizon_hours if samples else 0
    return_threshold = samples[0].return_threshold if samples else Decimal("0.0000")
    if sample_count == 0:
        return CalibrationReport(
            sample_count=0,
            horizon_hours=horizon_hours,
            return_threshold=return_threshold,
            accuracy=Decimal("0.0000"),
            brier_score=Decimal("0.0000"),
            coverage=Decimal("0.0000"),
            bins=[],
        )

    correct_count = sum(1 for sample in samples if sample.is_correct)
    brier_total = sum(
        (sample.raw_confidence - (Decimal("1.0000") if sample.is_correct else Decimal("0.0000"))) ** 2
        for sample in samples
    )
    bucketed: dict[int, list[CalibrationSample]] = {}
    for sample in samples:
        index = int(sample.raw_confidence * Decimal(bin_count))
        index = max(0, min(bin_count - 1, index))
        bucketed.setdefault(index, []).append(sample)

    bins: list[ReliabilityBin] = []
    for index in sorted(bucketed):
        bucket = bucketed[index]
        lower = _quantize(Decimal(index) / Decimal(bin_count))
        upper = _quantize(Decimal(index + 1) / Decimal(bin_count))
        bucket_correct = sum(1 for sample in bucket if sample.is_correct)
        average_confidence = _quantize(sum(sample.raw_confidence for sample in bucket) / Decimal(len(bucket)))
        accuracy = _quantize(Decimal(bucket_correct) / Decimal(len(bucket)))
        bins.append(
            ReliabilityBin(
                bin_lower=lower,
                bin_upper=upper,
                sample_count=len(bucket),
                average_confidence=average_confidence,
                accuracy=accuracy,
            )
        )

    return CalibrationReport(
        sample_count=sample_count,
        horizon_hours=horizon_hours,
        return_threshold=return_threshold,
        accuracy=_quantize(Decimal(correct_count) / Decimal(sample_count)),
        brier_score=_quantize(brier_total / Decimal(sample_count)),
        coverage=Decimal("1.0000"),
        bins=bins,
    )


def fit_confidence_calibrator(
    samples: list[CalibrationSample],
    *,
    min_samples: int = 30,
    bin_count: int = 10,
) -> CalibrationFitResult:
    if min_samples <= 0:
        raise ValueError("min_samples must be positive")

    report = build_reliability_report(samples, bin_count=bin_count)
    sample_count = len(samples)
    if sample_count < min_samples:
        return CalibrationFitResult(
            status="insufficient_samples",
            sample_count=sample_count,
            min_samples=min_samples,
            report=report,
            model=None,
        )

    grouped: dict[Decimal, list[CalibrationSample]] = {}
    for sample in samples:
        grouped.setdefault(_quantize(_clamp_probability(sample.raw_confidence)), []).append(sample)

    blocks: list[_IsotonicBlock] = []
    for raw_confidence in sorted(grouped):
        bucket = grouped[raw_confidence]
        correct_total = Decimal(sum(1 for sample in bucket if sample.is_correct))
        blocks.append(
            _IsotonicBlock(
                raw_confidence_lower=raw_confidence,
                raw_confidence_upper=raw_confidence,
                correct_total=correct_total,
                sample_count=len(bucket),
            )
        )
        while len(blocks) >= 2 and blocks[-2].average > blocks[-1].average:
            right = blocks.pop()
            left = blocks.pop()
            blocks.append(left.merge(right))

    points = [
        IsotonicCalibrationPoint(
            raw_confidence_lower=block.raw_confidence_lower,
            raw_confidence_upper=block.raw_confidence_upper,
            calibrated_confidence=_quantize(block.average),
            sample_count=block.sample_count,
        )
        for block in blocks
    ]
    model = IsotonicConfidenceCalibrator(
        points=points,
        sample_count=sample_count,
        horizon_hours=report.horizon_hours,
        return_threshold=report.return_threshold,
    )
    return CalibrationFitResult(
        status="fitted",
        sample_count=sample_count,
        min_samples=min_samples,
        report=report,
        model=model,
    )


def load_enabled_confidence_calibrator(parameters: dict[str, object]) -> IsotonicConfidenceCalibrator | None:
    payload = parameters.get("confidence_calibration")
    if not isinstance(payload, dict):
        return None
    if payload.get("enabled") is not True or payload.get("status") != "fitted":
        return None

    sample_count = int(payload.get("sample_count") or 0)
    min_samples = int(payload.get("min_samples") or 0)
    if min_samples <= 0 or sample_count < min_samples:
        return None

    raw_points = payload.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        return None

    points: list[IsotonicCalibrationPoint] = []
    for raw_point in raw_points:
        if not isinstance(raw_point, dict):
            return None
        points.append(
            IsotonicCalibrationPoint(
                raw_confidence_lower=_quantize(Decimal(str(raw_point["raw_confidence_lower"]))),
                raw_confidence_upper=_quantize(Decimal(str(raw_point["raw_confidence_upper"]))),
                calibrated_confidence=_quantize(Decimal(str(raw_point["calibrated_confidence"]))),
                sample_count=int(raw_point["sample_count"]),
            )
        )

    return IsotonicConfidenceCalibrator(
        points=points,
        sample_count=sample_count,
        horizon_hours=int(payload.get("horizon_hours") or 0),
        return_threshold=_quantize(Decimal(str(payload.get("return_threshold") or "0.0000"))),
    )


def calibrate_confidence_from_parameters(raw_confidence: Decimal, parameters: dict[str, object]) -> Decimal | None:
    calibrator = load_enabled_confidence_calibrator(parameters)
    if calibrator is None:
        return None
    return calibrator.calibrate(raw_confidence)
