# Tasks and Risk / 异步任务与风控

Celery workers execute background ingestion, analysis, signal/paper workflows, and monitoring. Celery beat schedules jobs; Redis carries task traffic and real-time Pub/Sub. Flower provides monitoring.

## Engineering boundaries

- Query features strictly before the requested UTC timestamp.
- Keep backtests bar-by-bar and reuse shared feature/signal entry points.
- Record `features_used` for every signal.
- Preserve independent risk checks, stops, position limits, and circuit-breaker behavior.
- Persist finance values as Decimal/Numeric and audit decisions append-only.
- Handle source or LLM failures through existing health, retry, and fallback paths rather than fabricated data.
- Optional calibration requires valid fitted metadata and sufficient samples.

## Default execution scope

Paper trading uses virtual funds. Broker submission and optional observation collection stay disabled in `.env.example`:

```dotenv
PHASE5_OBSERVATION_COLLECTION_ENABLED=false
PHASE5_EVIDENCE_WINDOW_STARTED=false
PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false
```

[Broker sandbox safety](../operations/broker_safety.md) and [observation collection](../operations/paper_observation.md) describe optional tools. Use them only with a separately configured paper account and explicit operator supervision; default startup does not require them.

## Verification

Existing tests cover time filtering, finance precision, features, signals, backtesting, paper execution, authentication, risk, and optional readiness tooling. CI uses disposable service instances. Running the tests or a smoke check must not connect to external broker accounts, submit orders, or enable scheduled observation collection.

Successful engineering checks establish implementation behavior. Profitability and predictive value require a separate research protocol and evidence.
