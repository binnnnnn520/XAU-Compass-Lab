"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { fetchNews } from "../lib/api";
import { formatPercent, formatUtcDateTime } from "../lib/format";
import { SectionCard } from "./cards";
import { ErrorPanel, EmptyPanel, LoadingPanel } from "./state-panels";

export function NewsPage() {
  const [items, setItems] = useState<Awaited<ReturnType<typeof fetchNews>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  async function loadNews() {
    setLoading(true);
    setError(null);

    try {
      setItems(await fetchNews({ page: 1, page_size: 24 }));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "News request failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadNews();
  }, []);

  const filtered = useMemo(() => {
    const query = deferredSearch.trim().toLowerCase();
    if (!items || query.length === 0) {
      return items?.items ?? [];
    }

    return items.items.filter((item) => {
      return (
        item.title.toLowerCase().includes(query) ||
        item.summary?.toLowerCase().includes(query) ||
        item.event_tags.some((tag) => tag.toLowerCase().includes(query))
      );
    });
  }, [deferredSearch, items]);

  if (loading) {
    return <LoadingPanel title="Loading news flow" copy="The app is reading `/api/v1/news`." />;
  }

  if (error) {
    return <ErrorPanel message={error} onRetry={() => void loadNews()} />;
  }

  if (!items) {
    return <EmptyPanel title="No news payload" copy="The backend did not return a valid news list." />;
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>News</h1>
          <p>Analyzed headlines and event tags from the existing paginated news API.</p>
        </div>
        <div className="status-pill">{items.total} total stories</div>
      </div>

      <SectionCard
        title="Filter feed"
        subtitle="Client-side search keeps the page responsive while preserving the original REST payload."
      >
        <div className="toolbar">
          <input
            className="input"
            type="search"
            value={search}
            placeholder="Search titles, summaries, or event tags"
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </SectionCard>

      <SectionCard title="Recent stories" subtitle="Loading, empty, and error states are explicitly handled for this page.">
        {filtered.length === 0 ? (
          <EmptyPanel
            title="No news matches this filter"
            copy={items.items.length === 0 ? "The API returned zero news rows." : "Try a broader search query."}
          />
        ) : (
          <div className="list">
            {filtered.map((item) => (
              <article key={item.id} className="list-item">
                <div className="list-item__meta">
                  <span>{item.source_name ?? "Unknown source"}</span>
                  <span>{formatUtcDateTime(item.published_at)}</span>
                  <span>{item.status}</span>
                </div>
                <h2 className="list-item__title">{item.title}</h2>
                <p className="subtle">{item.summary ?? "No summary stored for this article."}</p>
                <div className="chip-row">
                  <span className="chip" data-tone={item.sentiment?.label}>
                    {item.sentiment ? `${item.sentiment.label} ${formatPercent(item.sentiment.score, 0)}` : "No sentiment"}
                  </span>
                  {item.event_tags.length === 0 ? (
                    <span className="chip" data-tone="neutral">
                      No event tags
                    </span>
                  ) : (
                    item.event_tags.map((tag) => (
                      <span key={`${item.id}-${tag}`} className="chip">
                        {tag}
                      </span>
                    ))
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
