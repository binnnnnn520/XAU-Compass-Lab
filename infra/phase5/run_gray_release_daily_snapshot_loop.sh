#!/usr/bin/env bash
set -euo pipefail

: "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}"
: "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PHASE5_EVIDENCE_DIR="${PHASE5_EVIDENCE_DIR:-./evidence/phase5-gray-release}"
PHASE5_API_BASE_URL="${PHASE5_API_BASE_URL:-http://127.0.0.1:8000}"
PHASE5_DAILY_SNAPSHOT_INTERVAL_SECONDS="${PHASE5_DAILY_SNAPSHOT_INTERVAL_SECONDS:-86400}"
LOOP_LOG="${PHASE5_EVIDENCE_DIR}/daily_snapshot_loop.log"

mkdir -p "${PHASE5_EVIDENCE_DIR}"
cd "${REPO_ROOT}"

echo "Phase 5 daily snapshot loop started at $(date -u +"%Y-%m-%dT%H:%M:%SZ")" | tee -a "${LOOP_LOG}"

while true; do
  NOW_EPOCH="$(date -u +%s)"
  END_EPOCH="$(date -u -d "${PHASE5_WINDOW_END_UTC}" +%s)"
  if [ "${NOW_EPOCH}" -gt "${END_EPOCH}" ]; then
    echo "Phase 5 daily snapshot loop finished at $(date -u +"%Y-%m-%dT%H:%M:%SZ")" | tee -a "${LOOP_LOG}"
    exit 0
  fi

  set +e
  PHASE5_WINDOW_START_UTC="${PHASE5_WINDOW_START_UTC}" \
    PHASE5_WINDOW_END_UTC="${PHASE5_WINDOW_END_UTC}" \
    PHASE5_EVIDENCE_DIR="${PHASE5_EVIDENCE_DIR}" \
    PHASE5_API_BASE_URL="${PHASE5_API_BASE_URL}" \
    bash infra/phase5/write_gray_release_daily_snapshot.sh >> "${LOOP_LOG}" 2>&1
  SNAPSHOT_EXIT=$?
  set -e

  echo "snapshot_exit=${SNAPSHOT_EXIT} generated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")" | tee -a "${LOOP_LOG}"
  sleep "${PHASE5_DAILY_SNAPSHOT_INTERVAL_SECONDS}"
done
