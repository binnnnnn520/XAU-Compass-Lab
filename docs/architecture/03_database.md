# Database / 数据库

PostgreSQL schema changes are defined by the existing Alembic migrations under `apps/api/alembic/versions/`; ORM definitions are under `app/models/` and `app/auth/models.py`. Apply the migration chain before starting the application.

| Tables | Purpose |
| --- | --- |
| `news_sources`, `news_items` | Provider configuration, normalized news, processing status |
| `market_bars` | Timestamped symbol/timeframe OHLCV records |
| `sentiment_scores`, `event_tags` | Analyzer outputs and extracted events |
| `economic_events` | Available economic-event records used by features |
| `strategy_runs`, `model_versions` | Strategy configuration and fitted-model lifecycle |
| `signals` | Direction, confidence, reasons, and mandatory feature snapshots |
| `backtest_runs` | Experiment configuration, state, metrics, and result data |
| `paper_orders`, `paper_positions` | Simulated execution and positions |
| `risk_events`, `audit_logs` | Risk decisions and append-only audit evidence |
| `live_parallel_observations` | Optional paper/broker comparison observations; collection disabled by default |
| `users`, `roles` | Password hashes, local accounts, and role membership |

## Invariants

- Datetimes are timezone-aware UTC; `UTCDateTime` rejects naive values.
- Prices and persisted finance values use `Decimal`/SQL `Numeric`.
- News deduplication uses `UNIQUE(title_hash, source_id)`.
- `signals.features_used` preserves the inputs needed to trace decisions.
- Audit records cannot be edited or deleted through service operations; database retention guards remain in the migration chain.
- The user model stores salted password hashes rather than plaintext passwords.

## Migrations and tests

Run `python -m alembic upgrade head` from `apps/api`, or use the Docker command in the [startup guide](../startup_guide.md). Tests create and clean an isolated schema in a dedicated database. Never point test commands at another project's runtime data.

Current migrations and ORM definitions are authoritative for field-level details. Example or recorded research data does not create an entitlement to redistribute external news or market data.
