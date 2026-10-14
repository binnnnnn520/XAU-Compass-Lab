#!/usr/bin/env bash
set -euo pipefail

: "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}"
: "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}"

PHASE5_EVIDENCE_DIR="${PHASE5_EVIDENCE_DIR:-./evidence/phase5-gray-release}"
PHASE5_API_BASE_URL="${PHASE5_API_BASE_URL:-http://127.0.0.1:8000}"
GENERATED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
REPORT_URL="${PHASE5_API_BASE_URL%/}/api/v1/live/gray-release-report?start_at=${PHASE5_WINDOW_START_UTC}&end_at=${PHASE5_WINDOW_END_UTC}"

# The gray-release report endpoint requires an admin role. Re-login each run when
# admin credentials are provided (access tokens are short-lived).
PHASE5_REPORT_TOKEN="${PHASE5_ADMIN_TOKEN:-}"
if [ -z "${PHASE5_REPORT_TOKEN}" ] && [ -n "${PHASE5_ADMIN_USERNAME:-}" ] && [ -n "${PHASE5_ADMIN_PASSWORD:-}" ]; then
  PHASE5_REPORT_TOKEN="$(curl --fail --silent --show-error \
    -X POST "${PHASE5_API_BASE_URL%/}/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${PHASE5_ADMIN_USERNAME}\",\"password\":\"${PHASE5_ADMIN_PASSWORD}\"}" 2>/dev/null \
    | grep -o '"access_token":"[^"]*"' | head -1 | sed 's/.*"access_token":"//; s/"$//' || true)"
fi
REPORT_AUTH_ARGS=()
if [ -n "${PHASE5_REPORT_TOKEN}" ]; then
  REPORT_AUTH_ARGS=(-H "Authorization: Bearer ${PHASE5_REPORT_TOKEN}")
fi

mkdir -p "${PHASE5_EVIDENCE_DIR}/closeout"

curl --fail --silent --show-error \
  "${REPORT_AUTH_ARGS[@]}" \
  "${REPORT_URL}" \
  > "${PHASE5_EVIDENCE_DIR}/closeout/final_gray_release_report.json"

docker compose ps > "${PHASE5_EVIDENCE_DIR}/closeout/final_docker_compose_ps.txt"

DAILY_SNAPSHOT_COUNT="$(find "${PHASE5_EVIDENCE_DIR}/daily" -name snapshot_manifest.json -type f 2>/dev/null | wc -l | tr -d ' ')"

cat > "${PHASE5_EVIDENCE_DIR}/closeout/closeout_manifest.json" <<EOF
{
  "generated_at": "${GENERATED_AT}",
  "window_start_utc": "${PHASE5_WINDOW_START_UTC}",
  "window_end_utc": "${PHASE5_WINDOW_END_UTC}",
  "api_base_url": "${PHASE5_API_BASE_URL}",
  "daily_snapshot_count": ${DAILY_SNAPSHOT_COUNT},
  "final_report": "final_gray_release_report.json",
  "strategy_report_template": "docs/operations/phase5_strategy_report_template.md",
  "manual_closeout_required": true
}
EOF

echo "Phase 5 gray-release closeout evidence written to ${PHASE5_EVIDENCE_DIR}/closeout"
