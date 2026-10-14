import type {
  BacktestDetailData,
  BacktestListItemData,
  NewsListItemData,
  PaperOrderData,
  PaperPositionData,
  RiskEventData,
  SignalListItemData,
} from "./api";
import { formatPercent, toNumber } from "./format";

export interface ChartPoint {
  label: string;
  value: number;
  displayValue: string;
}

export interface StrategyOption {
  id: string;
  label: string;
}

function shortUtcLabel(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.valueOf())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(date);
}

export function buildSentimentTrend(newsItems: NewsListItemData[]) {
  return [...newsItems]
    .filter((item) => item.sentiment)
    .sort((left, right) => Date.parse(left.published_at) - Date.parse(right.published_at))
    .slice(-8)
    .map((item) => ({
      label: shortUtcLabel(item.published_at),
      value: toNumber(item.sentiment?.score),
      displayValue: formatPercent(toNumber(item.sentiment?.score), 1),
    }));
}

export function buildSignalConfidenceSeries(signalItems: SignalListItemData[]) {
  return [...signalItems]
    .sort((left, right) => Date.parse(left.signal_time) - Date.parse(right.signal_time))
    .slice(-10)
    .map((item) => ({
      label: shortUtcLabel(item.signal_time),
      value: toNumber(item.confidence),
      displayValue: formatPercent(item.confidence, 1),
    }));
}

export function buildEquityCurveSeries(backtest: BacktestDetailData | null) {
  if (!backtest) {
    return [];
  }

  return backtest.equity_curve.map(([timestamp, value]) => ({
    label: shortUtcLabel(timestamp),
    value: toNumber(value),
    displayValue: `$${toNumber(value).toFixed(2)}`,
  }));
}

export function summarizeSignalDirections(signalItems: SignalListItemData[]) {
  return ["BUY", "SELL", "HOLD"].map((direction) => ({
    direction,
    count: signalItems.filter((item) => item.direction === direction).length,
  }));
}

export function collectKnownStrategies(
  signalItems: SignalListItemData[],
  backtests: BacktestListItemData[],
): StrategyOption[] {
  const unique = new Map<string, string>();

  for (const item of signalItems) {
    unique.set(item.strategy_run_id, item.strategy_name);
  }

  for (const item of backtests) {
    unique.set(item.strategy_run_id, item.strategy_name);
  }

  return [...unique.entries()].map(([id, label]) => ({ id, label }));
}

export function summarizeOrderStatuses(orderItems: PaperOrderData[]) {
  return ["filled", "pending", "rejected"].map((status) => ({
    status,
    count: orderItems.filter((item) => item.status === status).length,
  }));
}

export function summarizePositionSides(positionItems: PaperPositionData[]) {
  return ["LONG", "SHORT"].map((side) => ({
    side,
    count: positionItems.filter((item) => item.side === side && item.status === "open").length,
  }));
}

export function summarizeRiskSeverities(eventItems: RiskEventData[]) {
  return ["critical", "warning", "info"].map((severity) => ({
    severity,
    count: eventItems.filter((item) => item.severity === severity).length,
  }));
}
