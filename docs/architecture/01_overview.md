# Architecture / 架构概览

XAU Compass Lab is a local research and paper-trading system focused on gold news. It provides an inspectable experiment workflow rather than a deployed trading service.

## Components

| Component | Responsibility |
| --- | --- |
| Next.js Web | Operator pages and authenticated API proxy |
| FastAPI | REST contracts, authentication, health, and risk operations |
| Celery worker / beat | Background ingestion, analysis, execution, and scheduled checks |
| PostgreSQL | News, bars, features used by signals, experiments, paper positions, audit evidence |
| Redis | Task broker and real-time Pub/Sub |
| Flower / Prometheus / Grafana | Optional operational visibility |

## Research flow

```text
Configured news and market providers
    → Normalized UTC records
    → Rules or optional external LLM analysis
    → Time-filtered feature snapshots
    → Shared strategy/signal entry points
    → Bar-by-bar backtests or risk-checked paper execution
    → Operator review and append-only audit evidence
```

Research, backtesting, and paper execution reuse the existing feature and signal contracts. Persisted finance values are Decimal/Numeric. Missing inputs, models, or sufficient calibration samples retain the existing safe fallback behavior.

## Scope

The code includes optional optimization, ensemble, monitoring, backup, DR, and guarded IBKR paper tooling. These capabilities depend on suitable configuration and data; their availability does not establish predictive advantage.

The default execution path uses virtual funds. Optional broker tools require a separately configured paper account; real-money execution is not enabled. See [capabilities and limitations](../capabilities.md), [startup](../startup_guide.md), [modules](02_modules.md), [database](03_database.md), [API](04_api.md), and [risk contracts](05_tasks_risk.md).
