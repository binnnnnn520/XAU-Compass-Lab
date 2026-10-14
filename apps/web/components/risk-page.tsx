"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchRiskEvents, fetchRiskStatus } from "../lib/api";
import { formatPercent, formatUtcDateTime } from "../lib/format";
import { summarizeRiskSeverities } from "../lib/view-models";
import { MetricCard, SectionCard } from "./cards";
import { ErrorPanel, EmptyPanel, LoadingPanel } from "./state-panels";

interface RiskState {
  status: Awaited<ReturnType<typeof fetchRiskStatus>>;
  events: Awaited<ReturnType<typeof fetchRiskEvents>>;
}

export function RiskPage() {
  const [state, setState] = useState<RiskState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [severity, setSeverity] = useState("");

  async function loadRiskState(selectedSeverity = severity) {
    setLoading(true);
    setError(null);

    try {
      const [status, events] = await Promise.all([
        fetchRiskStatus(),
        fetchRiskEvents({ page: 1, page_size: 20, severity: selectedSeverity || undefined }),
      ]);
      setState({ status, events });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Risk operations request failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadRiskState();
  }, []);

  const severitySummary = useMemo(() => summarizeRiskSeverities(state?.events.items ?? []), [state]);

  if (loading) {
    return <LoadingPanel title="Loading risk operations" copy="The app is reading `/api/v1/risk/*`." />;
  }

  if (error) {
    return <ErrorPanel message={error} onRetry={() => void loadRiskState()} />;
  }

  if (!state) {
    return <EmptyPanel title="No risk payload" copy="The backend returned no usable risk data." />;
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Risk Ops</h1>
          <p>Guardrail visibility across drawdown, circuit-breaker state, and recent risk events.</p>
        </div>
        <div className="status-pill" data-tone={state.status.trading_enabled ? "ok" : "warning"}>
          Trading {state.status.trading_enabled ? "enabled" : "restricted"}
        </div>
      </div>

      <div className="grid grid--metrics">
        <MetricCard
          label="Current Drawdown"
          value={formatPercent(state.status.current_drawdown, 2)}
          note={`Limit ${formatPercent(state.status.max_drawdown_limit, 2)}`}
        />
        <MetricCard
          label="Position Count"
          value={String(state.status.position_count)}
          note={`Limit ${state.status.position_limit}`}
        />
        <MetricCard
          label="Circuit Breaker"
          value={state.status.circuit_breaker_active ? "Active" : "Clear"}
          note={state.status.last_risk_event ? state.status.last_risk_event.type : "No prior events"}
        />
        <MetricCard
          label="Recent Criticals"
          value={String(severitySummary.find((item) => item.severity === "critical")?.count ?? 0)}
          note={`${state.events.total} event rows in current filter`}
        />
      </div>

      <div className="grid grid--two">
        <SectionCard title="Operator filter" subtitle="Existing pagination and severity filters from `GET /api/v1/risk/events`.">
          <div className="toolbar">
            <select
              className="input"
              value={severity}
              onChange={(event) => {
                const nextSeverity = event.target.value;
                setSeverity(nextSeverity);
                void loadRiskState(nextSeverity);
              }}
            >
              <option value="">All severities</option>
              <option value="critical">critical</option>
              <option value="warning">warning</option>
              <option value="info">info</option>
            </select>
          </div>
          <div className="callout">
            Flower runs separately under the compose stack for queue monitoring at <code>http://localhost:5555</code>.
          </div>
        </SectionCard>

        <SectionCard title="Last risk event" subtitle="Current REST status snapshot and latest event summary.">
          {state.status.last_risk_event === null ? (
            <EmptyPanel title="No risk events yet" copy="The risk engine has not emitted any persisted events." />
          ) : (
            <article className="list-item">
              <div className="list-item__meta">
                <span>{state.status.last_risk_event.type}</span>
                <span>{formatUtcDateTime(state.status.last_risk_event.time)}</span>
              </div>
              <h2 className="list-item__title">
                Circuit breaker {state.status.circuit_breaker_active ? "active" : "inactive"}
              </h2>
              <p className="subtle">
                Trading is currently {state.status.trading_enabled ? "enabled" : "restricted"} under the live risk snapshot.
              </p>
            </article>
          )}
        </SectionCard>
      </div>

      <SectionCard title="Risk event stream" subtitle="Persisted events from the existing risk API only.">
        {state.events.items.length === 0 ? (
          <EmptyPanel title="No events for this filter" copy="Broaden the severity filter or wait for the risk engine to emit events." />
        ) : (
          <div className="list">
            {state.events.items.map((item) => (
              <article key={item.id} className="list-item">
                <div className="list-item__meta">
                  <span>{item.event_type}</span>
                  <span>{item.severity}</span>
                  <span>{formatUtcDateTime(item.created_at)}</span>
                </div>
                <h2 className="list-item__title">{item.action_taken}</h2>
                <div className="chip-row">
                  <span className="chip" data-tone={item.severity === "critical" ? "negative" : item.severity === "warning" ? "neutral" : "positive"}>
                    {item.severity}
                  </span>
                  <span className="chip" data-tone="neutral">
                    Trigger {item.trigger_value ?? "n/a"}
                  </span>
                  <span className="chip" data-tone="neutral">
                    Threshold {item.threshold_value ?? "n/a"}
                  </span>
                </div>
                <p className="subtle">{item.description ?? "No description was persisted for this risk event."}</p>
              </article>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
