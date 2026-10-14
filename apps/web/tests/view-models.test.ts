import { describe, expect, it } from "vitest";
import {
  buildEquityCurveSeries,
  buildSentimentTrend,
  collectKnownStrategies,
  summarizeOrderStatuses,
  summarizePositionSides,
  summarizeRiskSeverities,
} from "../lib/view-models";
import { formatUtcDateTime } from "../lib/format";

describe("view models", () => {
  it("builds a sorted sentiment trend from analyzed news", () => {
    const points = buildSentimentTrend([
      {
        id: "2",
        title: "Later story",
        summary: null,
        source_id: null,
        source_name: "Reuters",
        published_at: "2026-04-08T02:00:00Z",
        status: "analyzed",
        sentiment: { label: "negative", score: "-0.30" },
        event_tags: [],
      },
      {
        id: "1",
        title: "Earlier story",
        summary: null,
        source_id: null,
        source_name: "Reuters",
        published_at: "2026-04-08T01:00:00Z",
        status: "analyzed",
        sentiment: { label: "positive", score: "0.45" },
        event_tags: [],
      },
    ]);

    expect(points).toHaveLength(2);
    expect(points[0]?.value).toBeCloseTo(0.45);
    expect(points[1]?.value).toBeCloseTo(-0.3);
  });

  it("builds equity points from persisted curve rows", () => {
    const points = buildEquityCurveSeries({
      id: "bt-1",
      strategy_run_id: "strategy-1",
      strategy_name: "sentiment_momentum_v1",
      start_date: "2025-01-01",
      end_date: "2025-12-31",
      status: "completed",
      initial_capital: "100000",
      final_capital: "112000",
      total_return: "0.12",
      max_drawdown: "-0.04",
      sharpe_ratio: "1.2",
      win_rate: "0.54",
      total_trades: 12,
      created_at: "2026-04-08T00:00:00Z",
      completed_at: "2026-04-08T00:01:00Z",
      error_message: null,
      equity_curve: [
        ["2025-01-01T00:00:00Z", "100000.00"],
        ["2025-01-02T00:00:00Z", "101250.50"],
      ],
      trade_log: [],
    });

    expect(points[1]?.displayValue).toBe("$101250.50");
  });

  it("deduplicates strategies discovered from signals and backtests", () => {
    const strategies = collectKnownStrategies(
      [
        {
          id: "signal-1",
          strategy_run_id: "strategy-1",
          strategy_name: "sentiment_momentum_v1",
          symbol: "XAUUSD",
          signal_time: "2026-04-08T00:00:00Z",
          direction: "BUY",
          strength: "0.8",
          confidence: "0.7",
          price_at_signal: "3100",
          reasoning: "Momentum is positive",
          source_type: "live",
          created_at: "2026-04-08T00:00:00Z",
        },
      ],
      [
        {
          id: "backtest-1",
          strategy_run_id: "strategy-1",
          strategy_name: "sentiment_momentum_v1",
          start_date: "2025-01-01",
          end_date: "2025-12-31",
          status: "completed",
          initial_capital: "100000",
          final_capital: "110000",
          total_return: "0.1",
          max_drawdown: "-0.03",
          sharpe_ratio: "1.1",
          win_rate: "0.5",
          total_trades: 10,
          created_at: "2026-04-08T00:00:00Z",
          completed_at: "2026-04-08T01:00:00Z",
        },
      ],
    );

    expect(strategies).toEqual([{ id: "strategy-1", label: "sentiment_momentum_v1" }]);
  });

  it("formats UTC datetimes explicitly", () => {
    expect(formatUtcDateTime("2026-04-08T01:02:03Z")).toContain("UTC");
  });

  it("summarizes paper order statuses for operator cards", () => {
    const summary = summarizeOrderStatuses([
      {
        id: "order-1",
        signal_id: "signal-1",
        symbol: "XAUUSD",
        side: "BUY",
        order_type: "MARKET",
        quantity: "1.0",
        price: "2300",
        limit_price: null,
        slippage: "0",
        commission: "0",
        status: "filled",
        reject_reason: null,
        filled_at: "2026-04-08T00:00:00Z",
        created_at: "2026-04-08T00:00:00Z",
      },
      {
        id: "order-2",
        signal_id: "signal-2",
        symbol: "XAUUSD",
        side: "SELL",
        order_type: "MARKET",
        quantity: "1.0",
        price: "2301",
        limit_price: null,
        slippage: "0",
        commission: "0",
        status: "rejected",
        reject_reason: "position_limit",
        filled_at: null,
        created_at: "2026-04-08T01:00:00Z",
      },
    ]);

    expect(summary).toEqual([
      { status: "filled", count: 1 },
      { status: "pending", count: 0 },
      { status: "rejected", count: 1 },
    ]);
  });

  it("counts only open positions by side", () => {
    const summary = summarizePositionSides([
      {
        id: "position-1",
        symbol: "XAUUSD",
        side: "LONG",
        quantity: "1.0",
        entry_price: "2300",
        current_price: "2310",
        unrealized_pnl: "10",
        realized_pnl: "0",
        status: "open",
        opened_at: "2026-04-08T00:00:00Z",
        closed_at: null,
        entry_order_id: "order-1",
        exit_order_id: null,
        created_at: "2026-04-08T00:00:00Z",
        updated_at: "2026-04-08T00:00:00Z",
      },
      {
        id: "position-2",
        symbol: "XAUUSD",
        side: "SHORT",
        quantity: "1.0",
        entry_price: "2290",
        current_price: "2285",
        unrealized_pnl: "5",
        realized_pnl: "0",
        status: "closed",
        opened_at: "2026-04-08T00:00:00Z",
        closed_at: "2026-04-08T01:00:00Z",
        entry_order_id: "order-2",
        exit_order_id: "order-3",
        created_at: "2026-04-08T00:00:00Z",
        updated_at: "2026-04-08T01:00:00Z",
      },
    ]);

    expect(summary).toEqual([
      { side: "LONG", count: 1 },
      { side: "SHORT", count: 0 },
    ]);
  });

  it("summarizes risk severities from the current event window", () => {
    const summary = summarizeRiskSeverities([
      {
        id: "event-1",
        event_type: "circuit_breaker",
        severity: "critical",
        trigger_value: "-0.8",
        threshold_value: "-0.7",
        action_taken: "reject_order",
        related_order_id: "order-1",
        description: "Threshold hit",
        metadata: {},
        created_at: "2026-04-08T00:00:00Z",
      },
      {
        id: "event-2",
        event_type: "drawdown_warning",
        severity: "warning",
        trigger_value: "-0.08",
        threshold_value: "-0.07",
        action_taken: "alert_only",
        related_order_id: null,
        description: "Drawdown warning",
        metadata: {},
        created_at: "2026-04-08T01:00:00Z",
      },
    ]);

    expect(summary).toEqual([
      { severity: "critical", count: 1 },
      { severity: "warning", count: 1 },
      { severity: "info", count: 0 },
    ]);
  });
});
