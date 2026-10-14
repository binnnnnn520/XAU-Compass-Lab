"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { createBacktest, fetchBacktestDetail, fetchBacktests, fetchSignals } from "../lib/api";
import { formatCurrency, formatPercent, formatUtcDate, formatUtcDateTime } from "../lib/format";
import { buildEquityCurveSeries, collectKnownStrategies } from "../lib/view-models";
import { MetricCard, SectionCard } from "./cards";
import { ErrorPanel, EmptyPanel, LoadingPanel } from "./state-panels";
import { SimpleLineChart } from "./simple-line-chart";

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

export function BacktestPage() {
  const [backtests, setBacktests] = useState<Awaited<ReturnType<typeof fetchBacktests>> | null>(null);
  const [signals, setSignals] = useState<Awaited<ReturnType<typeof fetchSignals>> | null>(null);
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof fetchBacktestDetail>> | null>(null);
  const [selectedBacktestId, setSelectedBacktestId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [submissionMessage, setSubmissionMessage] = useState<string | null>(null);
  const [form, setForm] = useState({
    strategy_run_id: "",
    start_date: "2025-01-01",
    end_date: todayIsoDate(),
    initial_capital: "100000.00",
    slippage_bps: "5",
    commission_bps: "2",
  });
  const [isPending, startTransition] = useTransition();

  async function loadBacktestPage() {
    setLoading(true);
    setError(null);

    try {
      const [backtestData, signalData] = await Promise.all([
        fetchBacktests({ page: 1, page_size: 12 }),
        fetchSignals({ page: 1, page_size: 50 }),
      ]);

      setBacktests(backtestData);
      setSignals(signalData);

      const knownStrategies = collectKnownStrategies(signalData.items, backtestData.items);
      const initialStrategy = knownStrategies[0]?.id ?? "";
      const initialBacktest = backtestData.items[0]?.id ?? "";

      setForm((current) => ({
        ...current,
        strategy_run_id: current.strategy_run_id || initialStrategy,
      }));
      setSelectedBacktestId((current) => current || initialBacktest);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Backtest page request failed.");
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(backtestId: string) {
    if (!backtestId) {
      setDetail(null);
      return;
    }

    setDetailError(null);
    try {
      setDetail(await fetchBacktestDetail(backtestId));
    } catch (loadError) {
      setDetailError(loadError instanceof Error ? loadError.message : "Could not load the selected backtest.");
    }
  }

  useEffect(() => {
    void loadBacktestPage();
  }, []);

  useEffect(() => {
    void loadDetail(selectedBacktestId);
  }, [selectedBacktestId]);

  useEffect(() => {
    if (!detail || !["pending", "running"].includes(detail.status)) {
      return;
    }

    const timer = window.setTimeout(() => {
      void loadDetail(detail.id);
      void loadBacktestPage();
    }, 5000);

    return () => window.clearTimeout(timer);
  }, [detail]);

  const strategyOptions = useMemo(
    () => collectKnownStrategies(signals?.items ?? [], backtests?.items ?? []),
    [backtests, signals],
  );
  const equitySeries = useMemo(() => buildEquityCurveSeries(detail), [detail]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmissionMessage(null);
    setError(null);

    try {
      const created = await createBacktest({
        strategy_run_id: form.strategy_run_id,
        start_date: form.start_date,
        end_date: form.end_date,
        initial_capital: Number(form.initial_capital),
        slippage_bps: Number(form.slippage_bps),
        commission_bps: Number(form.commission_bps),
      });

      const nextBacktests = await fetchBacktests({ page: 1, page_size: 12 });

      startTransition(() => {
        setBacktests(nextBacktests);
        setSelectedBacktestId(created.backtest_id);
        setSubmissionMessage(`${created.message} (${created.status})`);
      });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Backtest creation failed.");
    }
  }

  if (loading) {
    return <LoadingPanel title="Loading backtests" copy="The app is reading `/api/v1/backtest` and `/api/v1/signals`." />;
  }

  if (error && !backtests) {
    return <ErrorPanel message={error} onRetry={() => void loadBacktestPage()} />;
  }

  if (!backtests || !signals) {
    return <EmptyPanel title="No backtest payload" copy="The backend returned no usable backtest data." />;
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Backtests</h1>
          <p>Queue a run, inspect status, and visualize persisted equity and trade metrics.</p>
        </div>
        <div className="status-pill">{backtests.total} backtests</div>
      </div>

      {error ? (
        <div className="callout" data-tone="warning">
          {error}
        </div>
      ) : null}

      {submissionMessage ? <div className="callout">{submissionMessage}</div> : null}

      <SectionCard
        title="Create backtest"
        subtitle="No strategy endpoint exists yet, so the form uses known strategy IDs derived from current signals and recent backtests."
      >
        <form className="form-grid" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="strategy_run_id">Strategy run</label>
            <input
              id="strategy_run_id"
              className="input"
              list="strategy-options"
              value={form.strategy_run_id}
              onChange={(event) => setForm((current) => ({ ...current, strategy_run_id: event.target.value }))}
              placeholder="Strategy run UUID"
              required
            />
            <datalist id="strategy-options">
              {strategyOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </datalist>
            <span className="helper">
              {strategyOptions.length === 0
                ? "No strategy IDs discovered yet. Enter a known UUID manually."
                : `${strategyOptions.length} known strategies discovered from existing REST responses.`}
            </span>
          </div>
          <div className="field">
            <label htmlFor="start_date">Start date</label>
            <input
              id="start_date"
              className="input"
              type="date"
              value={form.start_date}
              onChange={(event) => setForm((current) => ({ ...current, start_date: event.target.value }))}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="end_date">End date</label>
            <input
              id="end_date"
              className="input"
              type="date"
              value={form.end_date}
              onChange={(event) => setForm((current) => ({ ...current, end_date: event.target.value }))}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="initial_capital">Initial capital</label>
            <input
              id="initial_capital"
              className="input"
              inputMode="decimal"
              value={form.initial_capital}
              onChange={(event) => setForm((current) => ({ ...current, initial_capital: event.target.value }))}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="slippage_bps">Slippage bps</label>
            <input
              id="slippage_bps"
              className="input"
              inputMode="numeric"
              value={form.slippage_bps}
              onChange={(event) => setForm((current) => ({ ...current, slippage_bps: event.target.value }))}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="commission_bps">Commission bps</label>
            <input
              id="commission_bps"
              className="input"
              inputMode="numeric"
              value={form.commission_bps}
              onChange={(event) => setForm((current) => ({ ...current, commission_bps: event.target.value }))}
              required
            />
          </div>
          <div className="button-row">
            <button className="button" type="submit" disabled={isPending}>
              {isPending ? "Submitting..." : "Create backtest"}
            </button>
          </div>
        </form>
      </SectionCard>

      <div className="detail-grid">
        <SectionCard title="Recent runs" subtitle="The selector and list are driven by `GET /api/v1/backtest`.">
          {backtests.items.length === 0 ? (
            <EmptyPanel title="No backtests found" copy="Create a run once strategy data is available." />
          ) : (
            <div className="list">
              {backtests.items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="list-item"
                  style={{ textAlign: "left" }}
                  onClick={() => setSelectedBacktestId(item.id)}
                >
                  <div className="list-item__meta">
                    <span>{item.strategy_name}</span>
                    <span>{item.status}</span>
                    <span>{formatUtcDateTime(item.created_at)}</span>
                  </div>
                  <h2 className="list-item__title">
                    {formatUtcDate(item.start_date)} to {formatUtcDate(item.end_date)}
                  </h2>
                  <div className="chip-row">
                    <span className="chip" data-tone="neutral">
                      Return {item.total_return === null ? "pending" : formatPercent(item.total_return, 2)}
                    </span>
                    <span className="chip" data-tone="neutral">
                      Trades {item.total_trades}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title="Selected run" subtitle="The detail panel uses `GET /api/v1/backtest/{id}`.">
          {detailError ? (
            <ErrorPanel title="Could not load backtest detail" message={detailError} />
          ) : !detail ? (
            <EmptyPanel title="Choose a run" copy="Select an existing run to inspect metrics and the equity curve." />
          ) : (
            <div className="grid">
              <div className="grid grid--metrics">
                <MetricCard label="Return" value={detail.total_return === null ? "--" : formatPercent(detail.total_return, 2)} note={detail.status} />
                <MetricCard label="Max drawdown" value={detail.max_drawdown === null ? "--" : formatPercent(detail.max_drawdown, 2)} note="Peak-to-trough" />
                <MetricCard label="Sharpe" value={detail.sharpe_ratio === null ? "--" : String(detail.sharpe_ratio)} note={`Win rate ${detail.win_rate === null ? "--" : formatPercent(detail.win_rate, 2)}`} />
                <MetricCard label="Final capital" value={detail.final_capital === null ? "--" : formatCurrency(detail.final_capital)} note={`${detail.total_trades} trades`} />
              </div>

              <SimpleLineChart points={equitySeries} title="Equity curve" color="#ad7c22" />

              {detail.error_message ? (
                <div className="callout" data-tone="warning">
                  {detail.error_message}
                </div>
              ) : null}

              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Side</th>
                      <th>Entry</th>
                      <th>Exit</th>
                      <th>Qty</th>
                      <th>Net PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.trade_log.length === 0 ? (
                      <tr>
                        <td colSpan={5}>No trade log rows were persisted for this run.</td>
                      </tr>
                    ) : (
                      detail.trade_log.slice(0, 8).map((row, index) => (
                        <tr key={`${row.entry_time}-${row.exit_time}-${index}`}>
                          <td>{row.side}</td>
                          <td>{formatUtcDateTime(row.entry_time)}</td>
                          <td>{formatUtcDateTime(row.exit_time)}</td>
                          <td>{row.quantity}</td>
                          <td>{formatCurrency(row.net_pnl)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
