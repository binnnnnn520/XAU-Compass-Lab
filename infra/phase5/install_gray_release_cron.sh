#!/usr/bin/env bash
set -euo pipefail

: "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}"
: "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}"

PHASE5_EVIDENCE_DIR="${PHASE5_EVIDENCE_DIR:-./evidence/phase5-gray-release}"
PHASE5_API_BASE_URL="${PHASE5_API_BASE_URL:-http://127.0.0.1:8000}"
PHASE5_DAILY_UTC_HOUR="${PHASE5_DAILY_UTC_HOUR:-23}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
CRON_MARKER="phase5-gray-release-daily"
CRON_COMMAND="cd ${REPO_ROOT} && PHASE5_WINDOW_START_UTC='${PHASE5_WINDOW_START_UTC}' PHASE5_WINDOW_END_UTC='${PHASE5_WINDOW_END_UTC}' PHASE5_EVIDENCE_DIR='${PHASE5_EVIDENCE_DIR}' PHASE5_API_BASE_URL='${PHASE5_API_BASE_URL}' infra/phase5/write_gray_release_daily_snapshot.sh >> '${PHASE5_EVIDENCE_DIR}/daily_cron.log' 2>&1"

mkdir -p "${PHASE5_EVIDENCE_DIR}"
CURRENT_CRON="$(mktemp)"
NEW_CRON="$(mktemp)"
trap 'rm -f "${CURRENT_CRON}" "${NEW_CRON}"' EXIT

crontab -l > "${CURRENT_CRON}" 2>/dev/null || true
grep -v "${CRON_MARKER}" "${CURRENT_CRON}" > "${NEW_CRON}" || true
{
  echo "# ${CRON_MARKER}"
  echo "CRON_TZ=UTC"
  echo "0 ${PHASE5_DAILY_UTC_HOUR} * * * ${CRON_COMMAND} # ${CRON_MARKER}"
} >> "${NEW_CRON}"

crontab "${NEW_CRON}"
echo "Installed ${CRON_MARKER} at ${PHASE5_DAILY_UTC_HOUR}:00 UTC"
