"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchSignals } from "../lib/api";
import { directionTone, formatCurrency, formatPercent, formatUtcDateTime } from "../lib/format";
import { buildSignalConfidenceSeries, summarizeSignalDirections } from "../lib/view-models";
import { MetricCard, SectionCard } from "./cards";
import { ErrorPanel, EmptyPanel, LoadingPanel } from "./state-panels";
import { SimpleLineChart } from "./simple-line-chart";

export function SignalsPage() {
  const [signals, setSignals] = useState<Awaited<ReturnType<typeof fetchSignals>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadSignals() {
    setLoading(true);
    setError(null);

    try {
      setSignals(await fetchSignals({ page: 1, page_size: 20 }));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Signals request failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSignals();
  }, []);

  const directionSummary = useMemo(() => summarizeSignalDirections(signals?.items ?? []), [signals]);
  const confidenceSeries = useMemo(() => buildSignalConfidenceSeries(signals?.items ?? []), [signals]);

  if (loading) {
    return <LoadingPanel title="Loading signals" copy="The app is reading `/api/v1/signals`." />;
  }

  if (error) {
    return <ErrorPanel message={error} onRetry={() => void loadSignals()} />;
  }

  if (!signals) {
    return <EmptyPanel title="No signal payload" copy="The backend returned no signals data." />;
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Signals</h1>
          <p>Current strategy decisions from the shared feature and signal pipeline.</p>
        </div>
        <div className="status-pill">{signals.total} total signals</div>
      </div>

      <div className="grid grid--metrics">
        {directionSummary.map((entry) => (
          <MetricCard
            key={entry.direction}
            label={entry.direction}
            value={String(entry.count)}
            note="Direction count in the current page window"
          />
        ))}
      </div>

      <div className="grid grid--two">
        <SectionCard title="Confidence trend" subtitle="Recent confidence readings from the REST signal list.">
          <SimpleLineChart points={confidenceSeries} title="Signal confidence" color="#8e4f40" />
        </SectionCard>

        <SectionCard title="Latest operator context" subtitle="Strategy name, signal time, and persisted reasoning.">
          {signals.items.length === 0 ? (
            <EmptyPanel title="No signals generated yet" copy="Wait for the analysis and signal tasks to populate data." />
          ) : (
            <div className="list">
              {signals.items.slice(0, 6).map((item) => (
                <article key={item.id} className="list-item">
                  <div className="list-item__meta">
                    <span>{item.strategy_name}</span>
                    <span>{item.symbol}</span>
                    <span>{formatUtcDateTime(item.signal_time)}</span>
                  </div>
                  <h2 className="list-item__title">
                    {item.direction} · {formatPercent(item.confidence, 1)}
                  </h2>
                  <div className="chip-row">
                    <span className="chip" data-tone={directionTone(item.direction)}>
                      Strength {formatPercent(item.strength, 1)}
                    </span>
                    <span className="chip" data-tone="neutral">
                      Price {item.price_at_signal ? formatCurrency(item.price_at_signal) : "n/a"}
                    </span>
                    <span className="chip" data-tone="neutral">
                      {item.source_type}
                    </span>
                  </div>
                  <p className="subtle">{item.reasoning}</p>
                </article>
              ))}
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
