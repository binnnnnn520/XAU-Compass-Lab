from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import math
from pathlib import Path
import sys
from typing import TextIO


METRIC_QUANTIZER = Decimal("0.0001")


@dataclass(frozen=True)
class WalkForwardSample:
    timestamp: datetime | str
    probability: Decimal
    realized_return: Decimal


@dataclass(frozen=True)
class WalkForwardResult:
    sample_count: int
    bars_processed: int
    total_trades: int
    win_rate: Decimal
    sharpe_ratio: Decimal
    max_drawdown: Decimal
    final_equity: Decimal
    passed: bool
    equity_curve: tuple[tuple[datetime, Decimal], ...]


def load_walk_forward_samples(path: str | Path) -> tuple[WalkForwardSample, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Walk-forward samples must be a non-empty JSON array.")
    return tuple(_sample_from_payload(item, index=index) for index, item in enumerate(payload))


def _sample_from_payload(item: object, *, index: int) -> WalkForwardSample:
    if not isinstance(item, dict):
        raise ValueError(f"sample[{index}] must be an object.")
    return WalkForwardSample(
        timestamp=_parse_utc_datetime(str(item["timestamp"])),
        probability=Decimal(str(item["probability"])).quantize(METRIC_QUANTIZER),
        realized_return=Decimal(str(item["realized_return"])).quantize(METRIC_QUANTIZER),
    )


def _parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone.")
    return parsed.astimezone(UTC)


def _sample_timestamp(sample: WalkForwardSample) -> datetime:
    if isinstance(sample.timestamp, datetime):
        if sample.timestamp.tzinfo is None:
            raise ValueError("timestamp must include a timezone.")
        return sample.timestamp.astimezone(UTC)
    return _parse_utc_datetime(sample.timestamp)


def run_walk_forward_validation(
    samples: tuple[WalkForwardSample, ...],
    *,
    buy_threshold: Decimal = Decimal("0.5200"),
    sell_threshold: Decimal = Decimal("0.4800"),
    min_sharpe: Decimal = Decimal("0.5000"),
    initial_equity: Decimal = Decimal("10000.0000"),
) -> WalkForwardResult:
    if not samples:
        raise ValueError("At least one walk-forward sample is required.")

    timestamps = tuple(_sample_timestamp(sample) for sample in samples)
    if tuple(sorted(timestamps)) != timestamps:
        raise ValueError("Walk-forward samples must be sorted by timestamp.")

    equity = initial_equity
    peak = initial_equity
    max_drawdown = Decimal("0.0000")
    strategy_returns: list[Decimal] = []
    wins = 0
    trades = 0
    equity_curve: list[tuple[datetime, Decimal]] = []

    for timestamp, sample in zip(timestamps, samples):
        direction = _direction(sample.probability, buy_threshold=buy_threshold, sell_threshold=sell_threshold)
        if direction == "BUY":
            strategy_return = sample.realized_return
            trades += 1
        elif direction == "SELL":
            strategy_return = -sample.realized_return
            trades += 1
        else:
            strategy_return = Decimal("0.0000")

        if direction != "HOLD" and strategy_return > Decimal("0"):
            wins += 1
        strategy_returns.append(strategy_return)
        equity = (equity * (Decimal("1") + strategy_return)).quantize(METRIC_QUANTIZER, rounding=ROUND_HALF_UP)
        peak = max(peak, equity)
        if peak > Decimal("0"):
            drawdown = ((equity - peak) / peak).quantize(METRIC_QUANTIZER, rounding=ROUND_HALF_UP)
            max_drawdown = min(max_drawdown, drawdown)
        equity_curve.append((timestamp, equity))

    sharpe_ratio = _sharpe_ratio(strategy_returns)
    win_rate = Decimal("0.0000") if trades == 0 else (Decimal(wins) / Decimal(trades)).quantize(METRIC_QUANTIZER)
    return WalkForwardResult(
        sample_count=len(samples),
        bars_processed=len(samples),
        total_trades=trades,
        win_rate=win_rate,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        final_equity=equity,
        passed=sharpe_ratio > min_sharpe,
        equity_curve=tuple(equity_curve),
    )


def _direction(probability: Decimal, *, buy_threshold: Decimal, sell_threshold: Decimal) -> str:
    if probability >= buy_threshold:
        return "BUY"
    if probability <= sell_threshold:
        return "SELL"
    return "HOLD"


def _sharpe_ratio(returns: list[Decimal]) -> Decimal:
    if len(returns) < 2:
        return Decimal("0.0000")
    values = [float(value) for value in returns]
    mean_return = sum(values) / len(values)
    variance = sum((value - mean_return) ** 2 for value in values) / (len(values) - 1)
    if variance == 0:
        return Decimal("0.0000")
    return Decimal(str(mean_return / math.sqrt(variance))).quantize(METRIC_QUANTIZER, rounding=ROUND_HALF_UP)


def result_to_dict(result: WalkForwardResult) -> dict[str, object]:
    return {
        "sample_count": result.sample_count,
        "bars_processed": result.bars_processed,
        "total_trades": result.total_trades,
        "win_rate": format(result.win_rate, "f"),
        "sharpe_ratio": format(result.sharpe_ratio, "f"),
        "max_drawdown": format(result.max_drawdown, "f"),
        "final_equity": format(result.final_equity, "f"),
        "passed": result.passed,
    }


def run_walk_forward_cli(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 1 walk-forward validation from recorded samples.")
    parser.add_argument("--samples", required=True, help="Path to walk-forward JSON samples.")
    parser.add_argument("--buy-threshold", default="0.52")
    parser.add_argument("--sell-threshold", default="0.48")
    parser.add_argument("--min-sharpe", default="0.5")
    args = parser.parse_args(argv)

    result = run_walk_forward_validation(
        load_walk_forward_samples(args.samples),
        buy_threshold=Decimal(str(args.buy_threshold)),
        sell_threshold=Decimal(str(args.sell_threshold)),
        min_sharpe=Decimal(str(args.min_sharpe)),
    )
    output = stdout or sys.stdout
    output.write(json.dumps(result_to_dict(result), indent=2, sort_keys=True))
    output.write("\n")
    return 0 if result.passed else 1


def main() -> None:
    raise SystemExit(run_walk_forward_cli())


if __name__ == "__main__":
    main()
