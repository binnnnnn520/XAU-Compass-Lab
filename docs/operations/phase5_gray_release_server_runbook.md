# Phase 5 Gray-Release Server Runbook

This advanced workflow is paused in XAU Compass Lab. It is retained as an opt-in reference, not part of default startup or completed production acceptance.

This runbook defines how to run the formal 14-day Phase 5 gray-release evidence window on a continuously available server.

Remote server entrypoint:

```powershell
ssh research-host
```

Local Windows + WSL entrypoint:

```powershell
wsl
cd /path/to/XAU-Compass-Lab
```

For local execution, run IBKR Gateway or TWS paper in the Windows GUI and run the formal Docker evidence stack inside WSL/tmux. Do not run IBKR Gateway inside WSL unless the operator explicitly chooses the more complex VNC/Xvfb path.

## 1. Declare The UTC Evidence Window

Before enabling collection, record the following in `docs/production_upgrade_status.md`:

- evidence window name
- UTC start time
- UTC end time
- runtime environment
- operator availability expectations

Use a UTC-bounded window such as:

```text
2026-05-20 00:00:00 UTC to 2026-06-02 23:59:59 UTC
```

## 2. Required Long-Running Services

Keep these services online for the full window:

- PostgreSQL
- Redis
- `api`
- `worker`
- `beat`
- IBKR Gateway paper or TWS paper

The Phase 5 gray-release window is invalid if the API, database, Redis, Celery worker, Celery beat, or the IBKR Gateway/TWS paper process is not continuously available for the declared interval.

On a 2c2g server, do not run optional observability/UI services during the formal window. Grafana, Prometheus, Flower, and the web UI are useful for operator visibility, but they are not part of the required evidence service set above and can destabilize a resource-constrained host when IBKR Gateway is running.

## 3. Required Environment Settings

Set these runtime values on the server before starting the formal evidence window:

```text
PHASE5_OBSERVATION_COLLECTION_ENABLED=true
PHASE5_EVIDENCE_WINDOW_STARTED=true
PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false
IBKR_PAPER_SANDBOX_MODE=paper
IBKR_PAPER_SANDBOX_HOST=<server-reachable-host>
IBKR_PAPER_SANDBOX_PORT=<paper-port>
IBKR_PAPER_SANDBOX_CLIENT_ID=<paper-client-id>
IBKR_PAPER_SANDBOX_ACCOUNT_ID=<paper-account-id>
```

Do not keep manual approval metadata or one-off close-position execution flags enabled for the 14-day observation window.

## 4. Start The Runtime Stack

From the repository root on the server:

```bash
export PHASE5_WINDOW_START_UTC="2026-05-20T00:00:00Z"
export PHASE5_WINDOW_END_UTC="2026-06-02T23:59:59Z"
export PHASE5_EVIDENCE_DIR="./evidence/phase5-gray-release"
export PHASE5_API_BASE_URL="http://127.0.0.1:8000"
export PHASE5_COMPOSE_SERVICES="postgres redis api worker beat"
infra/phase5/start_gray_release_window.sh
```

`PHASE5_COMPOSE_SERVICES` defaults to the required minimal service set:

```text
postgres redis api worker beat
```

Only add optional services such as `flower`, `prometheus`, or `grafana` on a server with enough CPU and memory. Do not add them on a 2c2g host.

Then verify the application is healthy:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/health
```

### Local WSL + tmux Start

Before using the local path:

- Install a WSL Ubuntu distro.
- Start Docker Desktop and enable WSL integration.
- Install `tmux` inside WSL.
- Start and log in to IBKR Gateway/TWS paper in the Windows GUI.
- Set `IBKR_PAPER_SANDBOX_HOST=host.docker.internal` and `IBKR_PAPER_SANDBOX_PORT=4002` in `.env`.
- Disable Windows sleep, hibernate, and automatic reboot for the full window.

Run the local preflight from WSL:

```bash
bash infra/phase5/preflight_local_wsl_gray_release.sh
```

Start the formal local tmux window:

```bash
export PHASE5_WINDOW_START_UTC="2026-06-10T00:00:00Z"
export PHASE5_WINDOW_END_UTC="2026-06-23T23:59:59Z"
export PHASE5_EVIDENCE_DIR="./evidence/phase5-gray-release-local"
export PHASE5_API_BASE_URL="http://127.0.0.1:8000"
export PHASE5_COMPOSE_SERVICES="postgres redis api worker beat"
bash infra/phase5/start_local_wsl_tmux_gray_release.sh
```

This starts a `phase5-gray-release` tmux session with:

- `runtime`: starts the minimal formal stack and follows `api worker beat` logs.
- `snapshots`: runs `infra/phase5/run_gray_release_daily_snapshot_loop.sh` once per day.
- `shell`: leaves an operator shell in the repository root.

Attach later with:

```bash
tmux attach -t phase5-gray-release
```

## 5. Observe The Evidence Window

The observation collector runs through Celery beat every 5 minutes in UTC. During the window, check:

- `worker` logs for successful collection runs
- `beat` logs for the scheduled task firing
- `api` health
- IBKR Gateway or TWS paper connectivity

The primary evidence path is the automated daily snapshot:

```bash
infra/phase5/write_gray_release_daily_snapshot.sh
```

Install it as a UTC cron job after the window variables are exported:

```bash
infra/phase5/install_gray_release_cron.sh
```

Each automated daily snapshot writes a timestamped directory under `./evidence/phase5-gray-release/daily/` with:

- `health.json`
- `gray_release_report.json`
- `docker_compose_ps.txt`
- `service_logs_tail.txt`
- `runtime_phase5_flags.txt`
- `snapshot_manifest.json`

Primary evidence API:

```text
GET /api/v1/live/gray-release-report
```

Use the report endpoint with UTC-bounded `start_at` and `end_at` values to monitor:

- observation count
- running days
- direction divergence
- average slippage
- Sharpe deviation
- risk event count
- acceptance blockers

## 6. Daily Operator Checks

Automated daily snapshot evidence is required. Human review is recommended at least once per UTC day, but a missed manual review does not invalidate the window by itself if the automated snapshot exists, the services stayed online, and a catch-up review records the missed day.

Review each snapshot for:

- the stack is still online
- `PHASE5_OBSERVATION_COLLECTION_ENABLED=true`
- `PHASE5_EVIDENCE_WINDOW_STARTED=true`
- `PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false`
- new observations are being written
- no unexpected risk events were created

If the operator cannot review daily, perform a catch-up review as soon as possible:

1. Inspect all unreviewed `snapshot_manifest.json` files.
2. Inspect the matching `gray_release_report.json` and `service_logs_tail.txt` files.
3. Record any gap, failed snapshot, or service outage in `docs/production_upgrade_status.md`.
4. Do not mark Phase 5 accepted if automated snapshots are missing for the declared window or if an outage broke continuous evidence.

## 7. Emergency Stop

If supervised runtime must stop, enable the kill path immediately:

```text
POST /api/v1/live/emergency-stop
```

The request must include a UTC `requested_at`, a reason, and any known open live position identifiers. After emergency stop:

- confirm live routing remains disabled
- freeze capital promotion
- inspect `audit_logs`
- inspect `risk_events`
- investigate before resuming

## 8. Window Closeout

At the end of the 14-day interval:

1. Pull the final `GET /api/v1/live/gray-release-report` snapshot for the declared UTC window:
   ```bash
   infra/phase5/finalize_gray_release_window.sh
   ```
2. Confirm `running_days >= 14`, Sharpe deviation `< 20%`, and zero risk events.
3. Generate the strategy report using the Phase 5 strategy report template.
4. Record the final evidence and acceptance decision in `docs/production_upgrade_status.md`.
