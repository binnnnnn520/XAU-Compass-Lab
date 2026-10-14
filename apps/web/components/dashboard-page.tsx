"use client";

import { useEffect, useState } from "react";
import { fetchEvents, fetchHealth, fetchNews, fetchSentimentAggregate, fetchSignals } from "../lib/api";
import { formatNumber, formatPercent, formatUtcDateTime } from "../lib/format";
import { buildSentimentTrend, buildSignalConfidenceSeries } from "../lib/view-models";
import {
  buildRealtimeSubscribePayload,
  buildRealtimeWebSocketUrl,
  parsePriceUpdate,
  parseRealtimeMessage,
  type PriceUpdate,
} from "../lib/websocket";
import { MetricCard, SectionCard } from "./cards";
import { ErrorPanel, EmptyPanel, LoadingPanel } from "./state-panels";
import { SimpleLineChart } from "./simple-line-chart";

interface DashboardState {
  health: Awaited<ReturnType<typeof fetchHealth>>;
  news: Awaited<ReturnType<typeof fetchNews>>;
  signals: Awaited<ReturnType<typeof fetchSignals>>;
  events: Awaited<ReturnType<typeof fetchEvents>>;
  sentiment: Awaited<ReturnType<typeof fetchSentimentAggregate>>;
}

type RealtimeStatus = "connecting" | "connected" | "degraded";

interface RealtimeState {
  status: RealtimeStatus;
  latestPrice: PriceUpdate | null;
  lastMessageAt: string | null;
}

export function DashboardPage() {
  const [state, setState] = useState<DashboardState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [realtime, setRealtime] = useState<RealtimeState>({
    status: "connecting",
    latestPrice: null,
    lastMessageAt: null,
  });

  async function loadDashboard() {
    setLoading(true);
    setError(null);

    try {
      const [health, news, signals, events, sentiment] = await Promise.all([
        fetchHealth(),
        fetchNews({ page: 1, page_size: 8, status: "analyzed" }),
        fetchSignals({ page: 1, page_size: 8 }),
        fetchEvents({ page: 1, page_size: 6 }),
        fetchSentimentAggregate("4h"),
      ]);
      setState({ health, news, signals, events, sentiment });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Dashboard request failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.WebSocket !== "function") {
      setRealtime((current) => ({ ...current, status: "degraded" }));
      return;
    }

    let closing = false;

    try {
      const socket = new window.WebSocket(buildRealtimeWebSocketUrl());

      socket.onopen = () => {
        if (closing) {
          return;
        }
        setRealtime((current) => ({ ...current, status: "connected" }));
        socket.send(JSON.stringify(buildRealtimeSubscribePayload()));
      };

      socket.onmessage = (event) => {
        if (closing || typeof event.data !== "string") {
          return;
        }

        const message = parseRealtimeMessage(event.data);
        if (!message) {
          return;
        }

        const price = parsePriceUpdate(message);
        setRealtime((current) => ({
          status: "connected",
          latestPrice: price ?? current.latestPrice,
          lastMessageAt: message.timestamp ?? current.lastMessageAt,
        }));
      };

      socket.onerror = () => {
        if (!closing) {
          setRealtime((current) => ({ ...current, status: "degraded" }));
        }
      };

      socket.onclose = () => {
        if (!closing) {
          setRealtime((current) => ({ ...current, status: "degraded" }));
        }
      };

      return () => {
        closing = true;
        socket.close();
      };
    } catch {
      setRealtime((current) => ({ ...current, status: "degraded" }));
    }
  }, []);

  if (loading) {
    return <LoadingPanel />;
  }

  if (error) {
    return <ErrorPanel message={error} onRetry={() => void loadDashboard()} />;
  }

  if (!state) {
    return <EmptyPanel title="No dashboard data" copy="The backend returned no usable data envelope." />;
  }

  const sentimentTrend = buildSentimentTrend(state.news.items);
  const signalConfidence = buildSignalConfidenceSeries(state.signals.items);
  const apiHealthy = state.health.db_connected && state.health.redis_connected && state.health.status === "healthy";
  const realtimeNote = realtime.latestPrice
    ? `${realtime.latestPrice.symbol} ${realtime.latestPrice.timeframe} ${formatNumber(realtime.latestPrice.price, 2)} at ${formatUtcDateTime(realtime.latestPrice.timestamp)}`
    : realtime.lastMessageAt
      ? `Last message ${formatUtcDateTime(realtime.lastMessageAt)}`
      : "Waiting for realtime stream";

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Dashboard</h1>
          <p>Front-end visibility across health, sentiment, news, event context, and latest signals.</p>
        </div>
        <div className="status-pill" data-tone={apiHealthy ? "ok" : "warning"}>
          API {apiHealthy ? "healthy" : "degraded"} · {formatUtcDateTime(state.health.timestamp)}
        </div>
      </div>

      <div className="grid grid--metrics">
        <MetricCard
          label="4h Avg Sentiment"
          value={formatNumber(state.sentiment.avg_score, 2)}
          note={`${state.sentiment.positive_count} positive / ${state.sentiment.negative_count} negative`}
        />
        <MetricCard
          label="Recent Signals"
          value={String(state.signals.total)}
          note={`${state.signals.items.filter((item) => item.direction === "BUY").length} BUY opportunities`}
        />
        <MetricCard
          label="Tracked Events"
          value={String(state.events.total)}
          note={state.sentiment.dominant_events.slice(0, 2).join(", ") || "No dominant tags yet"}
        />
        <MetricCard
          label="Recent News"
          value={String(state.news.total)}
          note={`Latest story ${state.news.items[0] ? formatUtcDateTime(state.news.items[0].published_at) : "unavailable"}`}
        />
        <MetricCard label="Realtime" value={realtime.status} note={realtimeNote} />
      </div>

      <div className="grid grid--two">
        <SectionCard title="Sentiment trend" subtitle="Derived from the latest analyzed news payload.">
          <SimpleLineChart points={sentimentTrend} title="Sentiment trend" color="#365d4c" />
        </SectionCard>

        <SectionCard title="Signal confidence" subtitle="Confidence history from the existing signals feed.">
          <SimpleLineChart points={signalConfidence} title="Signal confidence trend" color="#ad7c22" />
        </SectionCard>
      </div>

      <div className="grid grid--two">
        <SectionCard title="Recent news" subtitle="Last analyzed headlines with event tags and sentiment labels.">
          {state.news.items.length === 0 ? (
            <EmptyPanel title="No news yet" copy="Ingestion or analysis has not populated the feed." />
          ) : (
            <div className="list">
              {state.news.items.map((item) => (
                <article key={item.id} className="list-item">
                  <div className="list-item__meta">
                    <span>{item.source_name ?? "Unknown source"}</span>
                    <span>{formatUtcDateTime(item.published_at)}</span>
                    <span>{item.status}</span>
                  </div>
                  <h3 className="list-item__title">{item.title}</h3>
                  <p className="subtle">{item.summary ?? "No summary was persisted for this article."}</p>
                  <div className="chip-row">
                    <span className="chip" data-tone={item.sentiment?.label}>
                      {item.sentiment ? `${item.sentiment.label} ${formatPercent(item.sentiment.score, 0)}` : "No sentiment"}
                    </span>
                    {item.event_tags.map((tag) => (
                      <span key={tag} className="chip">
                        {tag}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title="Signals and events" subtitle="A compact operator view of the latest generated decisions.">
          <div className="list">
            {state.signals.items.slice(0, 4).map((item) => (
              <article key={item.id} className="list-item">
                <div className="list-item__meta">
                  <span>{item.strategy_name}</span>
                  <span>{item.symbol}</span>
                  <span>{formatUtcDateTime(item.signal_time)}</span>
                </div>
                <h3 className="list-item__title">
                  {item.direction} · {formatPercent(item.confidence, 0)} confidence
                </h3>
                <p className="subtle">{item.reasoning}</p>
              </article>
            ))}

            {state.events.items.slice(0, 3).map((item) => (
              <article key={item.id} className="list-item">
                <div className="list-item__meta">
                  <span>{item.tag_type}</span>
                  <span>{formatUtcDateTime(item.published_at)}</span>
                </div>
                <h3 className="list-item__title">{item.tag_value}</h3>
                <p className="subtle">{item.news_title}</p>
              </article>
            ))}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
