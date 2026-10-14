# Modules / 模块说明

Backend services live under `apps/api/app/services/`. This overview describes implemented responsibilities rather than future feature promises.

| Module | Responsibility |
| --- | --- |
| `news_ingestion` | Fetch configured feeds, normalize news, deduplicate, track source health |
| `market_ingestion` | Fetch and normalize market bars, select providers, refill configured lookback gaps |
| `llm_analysis` | Rules or optional LLM requests, structured parsing, caching, batching, retry/budget fallback |
| `feature_engine` | Build Decimal-safe feature snapshots using data available strictly before the requested timestamp |
| `signal_engine` | Rule/model/ensemble evaluation through shared signal entry points; persist `features_used` |
| `backtest_engine` | Process historical bars sequentially and compute experiment outcomes |
| `paper_execution` | Simulate orders and positions and apply exit behavior |
| `risk_engine` | Exposure, position-loss, duration, drawdown, and circuit-breaker checks |
| `optimization` / `calibration` | Bounded searches and fitted, sample-gated confidence calibration |
| `broker` | Paper interface and guarded IBKR paper verification; live placeholders stay unusable |
| `compliance` | Retention controls and strategy report generation |

Authentication lives under `app/auth/`; REST routes under `app/routes/`; background orchestration under `app/tasks/`. The Web application consumes the existing API rather than defining new backend behavior.

## Data boundaries

- News identity remains `UNIQUE(title_hash, source_id)`.
- Similar-title LLM caching is an optimization, not news deduplication.
- Source failures are observable and do not justify inventing bars or results.
- Sentiment output is a model interpretation of a news item, not a validated price forecast.
- Alternative-data features require suitable records in the database; the project does not promise a bundled live dataset.

See [API contracts](04_api.md) and [engineering constraints](05_tasks_risk.md).
