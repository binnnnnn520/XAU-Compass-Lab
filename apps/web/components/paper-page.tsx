"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchPaperAccount, fetchPaperOrders, fetchPaperPositions } from "../lib/api";
import { directionTone, formatCurrency, formatNumber, formatUtcDateTime } from "../lib/format";
import { summarizeOrderStatuses, summarizePositionSides } from "../lib/view-models";
import { MetricCard, SectionCard } from "./cards";
import { ErrorPanel, EmptyPanel, LoadingPanel } from "./state-panels";

interface PaperState {
  account: Awaited<ReturnType<typeof fetchPaperAccount>>;
  orders: Awaited<ReturnType<typeof fetchPaperOrders>>;
  positions: Awaited<ReturnType<typeof fetchPaperPositions>>;
}

export function PaperPage() {
  const [state, setState] = useState<PaperState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadPaperState() {
    setLoading(true);
    setError(null);

    try {
      const [account, orders, positions] = await Promise.all([
        fetchPaperAccount(),
        fetchPaperOrders({ page: 1, page_size: 12 }),
        fetchPaperPositions({ page: 1, page_size: 12 }),
      ]);
      setState({ account, orders, positions });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Paper trading request failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPaperState();
  }, []);

  const orderSummary = useMemo(() => summarizeOrderStatuses(state?.orders.items ?? []), [state]);
  const positionSummary = useMemo(() => summarizePositionSides(state?.positions.items ?? []), [state]);

  if (loading) {
    return <LoadingPanel title="Loading paper trading" copy="The app is reading `/api/v1/paper/*`." />;
  }

  if (error) {
    return <ErrorPanel message={error} onRetry={() => void loadPaperState()} />;
  }

  if (!state) {
    return <EmptyPanel title="No paper payload" copy="The backend returned no usable paper-trading data." />;
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Paper Trading</h1>
          <p>Operator visibility across account equity, current positions, and recent simulated orders.</p>
        </div>
        <div className="status-pill">
          {state.account.open_positions} open positions | {state.orders.total} orders
        </div>
      </div>

      <div className="grid grid--metrics">
        <MetricCard
          label="Total Equity"
          value={formatCurrency(state.account.total_equity)}
          note={`Cash ${formatCurrency(state.account.cash)}`}
        />
        <MetricCard
          label="Open Positions"
          value={String(state.account.open_positions)}
          note={`${positionSummary.find((item) => item.side === "LONG")?.count ?? 0} long / ${positionSummary.find((item) => item.side === "SHORT")?.count ?? 0} short`}
        />
        <MetricCard
          label="Unrealized PnL"
          value={formatCurrency(state.account.unrealized_pnl)}
          note={`Realized ${formatCurrency(state.account.realized_pnl)}`}
        />
        <MetricCard
          label="Today PnL"
          value={formatCurrency(state.account.today_pnl)}
          note={`${orderSummary.find((item) => item.status === "filled")?.count ?? 0} filled orders on page`}
        />
      </div>

      <div className="grid grid--two">
        <SectionCard title="Open positions" subtitle="Driven by `GET /api/v1/paper/positions` without frontend-only shaping.">
          {state.positions.items.length === 0 ? (
            <EmptyPanel title="No paper positions" copy="No simulated positions are open or persisted yet." />
          ) : (
            <div className="list">
              {state.positions.items.map((item) => (
                <article key={item.id} className="list-item">
                  <div className="list-item__meta">
                    <span>{item.symbol}</span>
                    <span>{item.side}</span>
                    <span>{formatUtcDateTime(item.opened_at)}</span>
                  </div>
                  <h2 className="list-item__title">
                    {formatNumber(item.quantity, 4)} @ {formatCurrency(item.entry_price)}
                  </h2>
                  <div className="chip-row">
                    <span className="chip" data-tone={directionTone(item.side === "LONG" ? "BUY" : "SELL")}>
                      {item.status}
                    </span>
                    <span className="chip" data-tone="neutral">
                      Current {formatCurrency(item.current_price)}
                    </span>
                    <span className="chip" data-tone={Number(item.unrealized_pnl ?? 0) >= 0 ? "positive" : "negative"}>
                      Unrealized {formatCurrency(item.unrealized_pnl)}
                    </span>
                  </div>
                  <p className="subtle">Realized PnL {formatCurrency(item.realized_pnl)}</p>
                </article>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title="Order flow" subtitle="Recent order outcomes from `GET /api/v1/paper/orders`.">
          {state.orders.items.length === 0 ? (
            <EmptyPanel title="No paper orders" copy="The execution pipeline has not created orders yet." />
          ) : (
            <div className="list">
              {state.orders.items.map((item) => (
                <article key={item.id} className="list-item">
                  <div className="list-item__meta">
                    <span>{item.symbol}</span>
                    <span>{item.side}</span>
                    <span>{formatUtcDateTime(item.created_at)}</span>
                  </div>
                  <h2 className="list-item__title">
                    {item.status} | {formatNumber(item.quantity, 4)} {item.order_type}
                  </h2>
                  <div className="chip-row">
                    <span
                      className="chip"
                      data-tone={item.status === "rejected" ? "negative" : item.status === "filled" ? "positive" : "neutral"}
                    >
                      {item.status}
                    </span>
                    <span className="chip" data-tone="neutral">
                      Price {item.price === null ? "n/a" : formatCurrency(item.price)}
                    </span>
                    <span className="chip" data-tone="neutral">
                      Commission {formatCurrency(item.commission)}
                    </span>
                  </div>
                  <p className="subtle">
                    {item.reject_reason
                      ? `Reject reason: ${item.reject_reason}`
                      : `Filled at ${formatUtcDateTime(item.filled_at)}`}
                  </p>
                </article>
              ))}
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
