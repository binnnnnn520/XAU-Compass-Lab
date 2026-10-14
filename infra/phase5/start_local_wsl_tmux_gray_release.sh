#!/usr/bin/env bash
set -euo pipefail

: "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}"
: "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PHASE5_TMUX_SESSION="${PHASE5_TMUX_SESSION:-phase5-gray-release}"
PHASE5_EVIDENCE_DIR="${PHASE5_EVIDENCE_DIR:-./evidence/phase5-gray-release}"
PHASE5_API_BASE_URL="${PHASE5_API_BASE_URL:-http://127.0.0.1:8000}"
PHASE5_COMPOSE_SERVICES="${PHASE5_COMPOSE_SERVICES:-postgres redis api worker beat}"

cd "${REPO_ROOT}"

bash infra/phase5/preflight_local_wsl_gray_release.sh

if tmux has-session -t "${PHASE5_TMUX_SESSION}" 2>/dev/null; then
  echo "tmux session already exists: ${PHASE5_TMUX_SESSION}" >&2
  exit 1
fi

export PHASE5_WINDOW_START_UTC
export PHASE5_WINDOW_END_UTC
export PHASE5_EVIDENCE_DIR
export PHASE5_API_BASE_URL
export PHASE5_COMPOSE_SERVICES

mkdir -p "${PHASE5_EVIDENCE_DIR}"

tmux new-session -d -s "${PHASE5_TMUX_SESSION}" -n runtime \
  "cd '${REPO_ROOT}' && export PHASE5_WINDOW_START_UTC='${PHASE5_WINDOW_START_UTC}' PHASE5_WINDOW_END_UTC='${PHASE5_WINDOW_END_UTC}' PHASE5_EVIDENCE_DIR='${PHASE5_EVIDENCE_DIR}' PHASE5_API_BASE_URL='${PHASE5_API_BASE_URL}' PHASE5_COMPOSE_SERVICES='${PHASE5_COMPOSE_SERVICES}' && bash infra/phase5/start_gray_release_window.sh && docker compose logs -f api worker beat"

tmux new-window -t "${PHASE5_TMUX_SESSION}" -n snapshots \
  "cd '${REPO_ROOT}' && export PHASE5_WINDOW_START_UTC='${PHASE5_WINDOW_START_UTC}' PHASE5_WINDOW_END_UTC='${PHASE5_WINDOW_END_UTC}' PHASE5_EVIDENCE_DIR='${PHASE5_EVIDENCE_DIR}' PHASE5_API_BASE_URL='${PHASE5_API_BASE_URL}' PHASE5_ADMIN_TOKEN='${PHASE5_ADMIN_TOKEN:-}' PHASE5_ADMIN_USERNAME='${PHASE5_ADMIN_USERNAME:-}' PHASE5_ADMIN_PASSWORD='${PHASE5_ADMIN_PASSWORD:-}' && bash infra/phase5/run_gray_release_daily_snapshot_loop.sh"

tmux new-window -t "${PHASE5_TMUX_SESSION}" -n shell \
  "cd '${REPO_ROOT}' && bash"

cat > "${PHASE5_EVIDENCE_DIR}/local_wsl_tmux_manifest.json" <<EOF
{
  "tmux_session": "${PHASE5_TMUX_SESSION}",
  "window_start_utc": "${PHASE5_WINDOW_START_UTC}",
  "window_end_utc": "${PHASE5_WINDOW_END_UTC}",
  "evidence_dir": "${PHASE5_EVIDENCE_DIR}",
  "api_base_url": "${PHASE5_API_BASE_URL}",
  "compose_services": "${PHASE5_COMPOSE_SERVICES}",
  "ibkr_runtime_location": "Windows GUI",
  "started_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF

echo "Phase 5 local WSL tmux session started: ${PHASE5_TMUX_SESSION}"
echo "Attach with: tmux attach -t ${PHASE5_TMUX_SESSION}"
