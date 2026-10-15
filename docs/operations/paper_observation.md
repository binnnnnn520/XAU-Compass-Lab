# Paper/Broker Observation Guide / 模拟账户观测指南

Use this optional workflow to collect paper/broker comparison diagnostics over a UTC-bounded research interval. It requires your own IBKR paper account and continuously running services. It is not part of default startup and does not submit broker orders.

本指南用于可选的模拟账户观测与诊断。自行选择研究时段，记录运行环境和数据缺口；不要将观测报告解释为收益保证或真实资金交易授权。

## 1. Prepare an isolated runtime

Required services:

- PostgreSQL and Redis
- `api`, `worker`, and Celery `beat`
- IBKR Gateway paper or TWS paper

Choose a host with enough memory for the database, worker, and Gateway/TWS. Add optional UI or monitoring services only when resources permit. Keep the machine awake and record service outages; observation timestamps alone cannot prove continuous availability.

Follow [startup](../startup_guide.md) for secrets, migrations, and administrator initialization. Use a paper account, keep credentials outside Git, and review [broker safety](broker_safety.md).

## 2. Configure collection

Set these values in the local runtime environment only when intentionally collecting observations:

```dotenv
PHASE5_OBSERVATION_COLLECTION_ENABLED=true
PHASE5_EVIDENCE_WINDOW_STARTED=true
PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false
IBKR_PAPER_SANDBOX_MODE=paper
IBKR_PAPER_SANDBOX_HOST=<reachable-host>
IBKR_PAPER_SANDBOX_PORT=<paper-port>
IBKR_PAPER_SANDBOX_CLIENT_ID=<paper-client-id>
IBKR_PAPER_SANDBOX_ACCOUNT_ID=<paper-account-id>
```

The second flag controls report diagnostics. Neither collection flag enables order submission. Do not set manual-approval or close-position execution flags for this workflow.

## 3. Select the interval and start services

Run from the repository root in Bash on Linux or WSL. Enter timezone-aware UTC timestamps such as `YYYY-MM-DDTHH:MM:SSZ`; choose the interval for your experiment.

```bash
read -r -p 'Start UTC: ' PHASE5_WINDOW_START_UTC
read -r -p 'End UTC: ' PHASE5_WINDOW_END_UTC
export PHASE5_WINDOW_START_UTC PHASE5_WINDOW_END_UTC
export PHASE5_EVIDENCE_DIR="./evidence/paper-observation"
export PHASE5_API_BASE_URL="http://127.0.0.1:8000"
export PHASE5_COMPOSE_SERVICES="postgres redis api worker beat"
bash infra/phase5/start_gray_release_window.sh
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health
```

The start script enables collection and keeps paper order execution disabled. Confirm these flags in the running `api`, `worker`, and `beat` containers after startup. Output includes a UTC interval manifest and initial service diagnostics under the chosen evidence directory.

### Windows with WSL and tmux

- Enable Docker Desktop's WSL integration and install `tmux` in the WSL distribution.
- Run IBKR Gateway/TWS paper in the Windows GUI.
- Configure a container-reachable address, typically `host.docker.internal`, and the configured paper port. Do not assume the Gateway's port or firewall rules match an example.
- Run the preflight, then use the same exported interval variables:

```bash
bash infra/phase5/preflight_local_wsl_gray_release.sh
bash infra/phase5/start_local_wsl_tmux_gray_release.sh
tmux attach -t phase5-gray-release
```

The tmux starter opens runtime logs, a daily snapshot loop, and an operator shell. The snapshot loop is `infra/phase5/run_gray_release_daily_snapshot_loop.sh`. Do not also schedule cron snapshots unless duplicate collection is intentional.

## 4. Authenticate and capture diagnostics

The report endpoint requires an administrator token. The snapshot helpers accept `PHASE5_ADMIN_TOKEN`, or log in using `PHASE5_ADMIN_USERNAME` and `PHASE5_ADMIN_PASSWORD`. Tokens expire; use a protected runtime environment rather than putting credentials in commands, logs, or repository files.

For an interactive Bash session:

```bash
read -r -p 'Administrator username: ' PHASE5_ADMIN_USERNAME
read -r -s -p 'Administrator password: ' PHASE5_ADMIN_PASSWORD
export PHASE5_ADMIN_USERNAME PHASE5_ADMIN_PASSWORD
bash infra/phase5/write_gray_release_daily_snapshot.sh
```

Each automated daily snapshot writes a timestamped directory under `$PHASE5_EVIDENCE_DIR/daily/` containing:

- `health.json` and `gray_release_report.json`
- `docker_compose_ps.txt` and `service_logs_tail.txt`
- `runtime_phase5_flags.txt`
- `snapshot_manifest.json`, including command exit statuses

The Celery observation task is scheduled every five minutes. Check worker and beat logs, API health, paper Gateway/TWS connectivity, snapshot status, and incoming observations.

The optional UTC cron installer is:

```bash
bash infra/phase5/install_gray_release_cron.sh
```

It installs a daily snapshot job, not an authentication service. It does not copy administrator credentials into cron; arrange a protected runtime environment for scheduled authentication. Review its generated command and paths before using it. The tmux loop is an alternative that inherits the interactive session environment.

## 5. Interpret and review

`GET /api/v1/live/gray-release-report` accepts UTC `start_at` and `end_at` query parameters. It returns observation counts, running-day estimates, direction divergence, slippage, Sharpe comparison, risk events, and diagnostic fields such as `acceptance_ready` and `acceptance_blockers`.

These field names refer to built-in guard checks. They are not release requirements, investment conclusions, or permission to enable a real-money broker. Missing observations, invalid comparison inputs, and dry runs must remain distinguishable from actual paper fills.

Review snapshots and record gaps or service outages in your own experiment log. A missed manual review does not replace an automated snapshot; perform a catch-up review of every unreviewed manifest, report, and log. Do not describe a time span between two records as uninterrupted uptime.

## 6. Stop and summarize

Capture the final report for the same interval:

```bash
bash infra/phase5/finalize_gray_release_window.sh
```

Use the [strategy report template](strategy_report_template.md) to record data coverage, configuration, metrics, and limitations. Keep raw runtime files and account details private.

Then disable collection in the runtime environment, recreate the affected services, and confirm all three flags are false. Stop the snapshot loop and remove the optional cron entry if installed. Unset administrator credentials when no longer needed.

If an urgent halt is required, an administrator can call `POST /api/v1/live/emergency-stop`; follow [the stop procedure](broker_safety.md#stop-procedure) and independently inspect the broker account.
