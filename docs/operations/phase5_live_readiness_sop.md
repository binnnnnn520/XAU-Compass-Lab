# Phase 5 Live Readiness SOP

Baseline: `phase4-accepted-20260430`.

This runbook governs Phase 5 live-readiness work. It does not authorize immediate live order routing. Do not configure real broker credentials by default, and do not enable live trading unless every safety gate below is satisfied and recorded in `docs/production_upgrade_status.md`.

## Safety Gates

- Live trading defaults to disabled.
- The kill switch must block all live order attempts while enabled.
- Live mode forces `manual_approval_required` for every order.
- Daily notional exposure must be capped with Decimal math.
- Initial rollout must stay at 1% capital until promotion criteria are met.
- No high-notional or low-confidence live order may bypass administrator approval.

## IBKR Paper Sandbox Adapter

- The IBKR paper sandbox adapter is unavailable by default.
- Sandbox access may only be read from environment variables, never committed credentials:
  `IBKR_PAPER_SANDBOX_MODE=paper`, `IBKR_PAPER_SANDBOX_HOST`,
  `IBKR_PAPER_SANDBOX_PORT`, `IBKR_PAPER_SANDBOX_CLIENT_ID`, and
  `IBKR_PAPER_SANDBOX_ACCOUNT_ID`.
- The adapter must route orders through the live readiness and live broker routing guards before any client call.
- The adapter health check may call only an injected paper sandbox client and must not include account IDs,
  tokens, passwords, or raw client exceptions in returned diagnostics.
- The account snapshot path is read-only, requires a healthy paper sandbox connection, and must return
  Decimal-safe finance fields without exposing account IDs or credentials.
- The `ibapi` paper client is a read-only Phase 5.11 adapter. It may request current time and account
  summary from TWS/Gateway paper, but its order method must remain disabled.
- When IBKR account summary omits realized or unrealized PnL tags, record those fields as Decimal zero
  in the read-only snapshot rather than treating the account as unhealthy.
- The order lifecycle dry-run is preview-only. It must pass live readiness, broker routing, manual approval,
  health-check, and account snapshot guards before mapping submitted/accepted/cancelled states, and it must
  not submit, cancel, or close any real broker order.
- Controlled IBKR paper order execution is disabled by default through
  `PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false`. Enable it only for an operator-supervised paper-account
  verification run after recording manual approval metadata. This path must remain paper-only, must pass live
  readiness, routing, credential, health-check, and account snapshot guards, and must not be triggered by the
  strategy loop.
- The direct IBKR live broker placeholder remains blocked until real broker readiness is explicitly accepted.

## Gray Release

Run paper and live observations in parallel before any capital increase.

The formal 14-day evidence window has not started by default. It starts only when an operator explicitly
chooses a continuous runtime window and keeps the required API, database, broker gateway, and observation
collection process online for that window. Development work may continue before that window starts, but those
development-only checks do not count as acceptance evidence.

For the server-hosted continuous-window procedure, use `docs/operations/phase5_gray_release_server_runbook.md`.

Required paper/live divergence report fields:

- Direction divergence rate.
- Order latency difference.
- Actual slippage in basis points.
- Paper Sharpe versus live Sharpe deviation.
- Risk event count.

Each parallel observation must be persisted with UTC signal/order/observation timestamps, Decimal-safe paper and
live prices, Decimal-safe order notional, guard status, dry-run status, and the risk-event count for that
observation window. These rows are evidence only; they do not authorize real broker order routing.

The automatic observation collection task is disabled by default. Set
`PHASE5_OBSERVATION_COLLECTION_ENABLED=true` only when the operator intends to run the collection process.
Until a formal evidence window is declared in `docs/production_upgrade_status.md`, automatically collected
development rows remain operational checks rather than acceptance evidence.

The gray-release report endpoint is `GET /api/v1/live/gray-release-report`. It reads persisted
`live_parallel_observations`, returns Decimal-safe divergence metrics in the unified API envelope, and includes
explicit acceptance blocker codes. `PHASE5_EVIDENCE_WINDOW_STARTED=false` remains the default; set it to `true`
only after the formal evidence window has been declared in `docs/production_upgrade_status.md`.

Capital may only be promoted when:

- The parallel run has covered at least 14 days.
- Paper/live Sharpe deviation is less than 20%.
- There are no risk events.
- Paper/live direction divergence is zero for the reviewed promotion window.

## Disaster Recovery

Phase 5 readiness target:

- RTO < 1 hour.
- RPO < 1 hour.
- PostgreSQL recovery must use the existing backup/restore rehearsal flow in `infra/backup`.
- Redis recovery must preserve the ability to disable live order routing via the kill switch.
- A restore rehearsal must be run against an isolated database, never production.

## Compliance

- Trading logs for orders, positions, and risk events must be retained for at least 5 years.
- `audit_logs append-only` remains mandatory.
- Alembic revision `20260501_0012` enforces Phase 5 retention in PostgreSQL:
  `audit_logs` update/delete attempts are rejected, and delete attempts on `risk_events`, `paper_orders`,
  `paper_positions`, and `live_parallel_observations` are rejected until the row has passed its 5-year
  retention window.
- Strategy reports must use `docs/operations/phase5_strategy_report_template.md` or the
  `build_strategy_report_markdown(...)` generator, and must include strategy version, backtest evidence, gray-release
  evidence, retention evidence, and any live-readiness decision that changed capital allocation.
- Every live-readiness decision must include the actor, UTC timestamp, old value, new value, and reason.

## Stop Procedure

1. Enable the kill switch.
2. If API access is available, an administrator triggers `POST /api/v1/live/emergency-stop` with a UTC `requested_at`, reason, and the known open live position identifiers.
3. Confirm new live orders are rejected by the readiness gate and live broker routing remains disabled.
4. Freeze capital promotion.
5. Confirm the emergency stop wrote both `audit_logs` and `risk_events`.
6. Review open positions and use the broker-specific close workflow only after manual approval.

The emergency-stop API records the halt request and close-all-positions intent. It does not configure real broker credentials and does not bypass broker-specific manual approval for actual close workflows.
