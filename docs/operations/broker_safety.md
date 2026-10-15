# Broker Sandbox Safety / 券商模拟账户安全

The default research workflow uses virtual funds and does not connect to a broker. These optional tools inspect or verify an IBKR paper account under operator supervision. They do not provide an enabled real-money broker connection.

默认研究流程使用虚拟资金。以下工具仅面向自行配置的 IBKR 模拟账户，须由操作者监督使用，不属于首次启动所需步骤。

## Safety controls

- Do not configure real broker credentials by default.
- The kill switch blocks guarded order attempts while enabled.
- The readiness guard requires `manual_approval_required` for live-mode requests.
- Daily notional exposure is limited with Decimal math.
- `max_initial_capital_fraction` defaults to `0.0100` in the readiness configuration. It is a guard limit, not an instruction to allocate funds.
- Orders cannot bypass role, confidence, exposure, or manual-approval checks.
- The direct IBKR live broker is a blocked placeholder; paper tools must not be treated as a live-account route.

## Connection and inspection

Configure a paper Gateway/TWS connection only through local environment variables:

```dotenv
IBKR_PAPER_SANDBOX_MODE=paper
IBKR_PAPER_SANDBOX_HOST=<reachable-host>
IBKR_PAPER_SANDBOX_PORT=<paper-port>
IBKR_PAPER_SANDBOX_CLIENT_ID=<paper-client-id>
IBKR_PAPER_SANDBOX_ACCOUNT_ID=<paper-account-id>
```

- Health checks use the paper client and redact account identifiers, credentials, and raw client exceptions.
- Account snapshots require a healthy paper connection and return Decimal-safe values.
- The read-only `ibapi` client may request current time and account summaries; its order method remains disabled.
- Missing realized or unrealized PnL summary tags are represented as Decimal zero. Inspect the available fields before interpreting the snapshot.
- Lifecycle dry runs pass readiness, routing, approval, health, and snapshot guards but do not submit, cancel, or close broker orders.

## Supervised paper orders

`PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false` is the default. Set it only for an explicitly supervised paper-account verification command, with command-local approval metadata. Do not enable it in the strategy loop or leave it active afterward.

Follow [IBKR paper close-position verification](ibkr_paper_verification.md) for pre-checks, execution, cleanup, and expected output. This tool can submit a paper order; a dry run and an execution check are different operations.

## Optional observation collection

[Observation collection](paper_observation.md) compares persisted paper/broker diagnostics without enabling broker order submission. Collection and its report flag default to disabled:

```dotenv
PHASE5_OBSERVATION_COLLECTION_ENABLED=false
PHASE5_EVIDENCE_WINDOW_STARTED=false
```

`GET /api/v1/live/gray-release-report` reads `live_parallel_observations`. Records include UTC timestamps, Decimal-safe prices and notional, direction, latency, slippage, guard and dry-run states, and risk-event counts. Its readiness fields are diagnostic guard outputs, not proof of continuous service, profitability, or permission to trade.

## Recovery and data retention

- Rehearse PostgreSQL restores using [the backup tools](../../infra/backup/README.md) and an isolated database.
- Use the [isolated recovery stack](../../infra/dr/README.md) for PostgreSQL replication and Redis Sentinel checks.
- Retain the ability to stop routing during recovery; do not bypass the kill switch to make a test pass.
- `audit_logs append-only` is mandatory.
- Alembic revision `20260501_0012` rejects audit-row updates/deletes and prevents deletion of rows younger than 5 years in `risk_events`, `paper_orders`, `paper_positions`, and `live_parallel_observations`.
- These are implemented data-retention controls, not a claim of regulatory compliance.
- Record research results with the [strategy report template](strategy_report_template.md). Preserve actor, UTC timestamp, reason, and audit references for configuration changes.

## Stop procedure

1. Enable the kill switch.
2. An administrator can call `POST /api/v1/live/emergency-stop` with UTC `requested_at`, a reason, and any known open position identifiers.
3. Confirm guarded order requests are rejected and broker execution is disabled.
4. Inspect `audit_logs`, `risk_events`, and broker-side open orders and positions.
5. Use a broker-specific close workflow only after manual approval.

The emergency-stop API records the halt request and close-all-positions intent. It does not guarantee that an external broker position is closed, configure credentials, or bypass broker-specific approval. Verify the actual paper-account state separately.
