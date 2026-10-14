#!/usr/bin/env bash
set -euo pipefail

: "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}"
: "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}"

PHASE5_EVIDENCE_DIR="${PHASE5_EVIDENCE_DIR:-./evidence/phase5-gray-release}"
PHASE5_API_BASE_URL="${PHASE5_API_BASE_URL:-http://127.0.0.1:8000}"
GENERATED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
SNAPSHOT_ID="$(date -u +"%Y%m%dT%H%M%SZ")"
SNAPSHOT_DIR="${PHASE5_EVIDENCE_DIR}/daily/${SNAPSHOT_ID}"
REPORT_URL="${PHASE5_API_BASE_URL%/}/api/v1/live/gray-release-report?start_at=${PHASE5_WINDOW_START_UTC}&end_at=${PHASE5_WINDOW_END_UTC}"

# The gray-release report endpoint requires an admin role. Access tokens expire in
# ~15 minutes, so re-login each run when admin credentials are provided.
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

mkdir -p "${SNAPSHOT_DIR}"

set +e
curl --fail --silent --show-error \
  "${PHASE5_API_BASE_URL%/}/api/v1/health" \
  > "${SNAPSHOT_DIR}/health.json" 2> "${SNAPSHOT_DIR}/health.stderr"
HEALTH_EXIT=$?

curl --fail --silent --show-error \
  "${REPORT_AUTH_ARGS[@]}" \
  "${REPORT_URL}" \
  > "${SNAPSHOT_DIR}/gray_release_report.json" 2> "${SNAPSHOT_DIR}/gray_release_report.stderr"
REPORT_EXIT=$?

docker compose ps > "${SNAPSHOT_DIR}/docker_compose_ps.txt" 2> "${SNAPSHOT_DIR}/docker_compose_ps.stderr"
COMPOSE_PS_EXIT=$?

docker compose logs --since 24h --tail 200 api worker beat \
  > "${SNAPSHOT_DIR}/service_logs_tail.txt" 2> "${SNAPSHOT_DIR}/service_logs_tail.stderr"
LOGS_EXIT=$?

{
  echo "PHASE5_OBSERVATION_COLLECTION_ENABLED=$(docker compose exec -T api printenv PHASE5_OBSERVATION_COLLECTION_ENABLED 2>/dev/null)"
  echo "PHASE5_EVIDENCE_WINDOW_STARTED=$(docker compose exec -T api printenv PHASE5_EVIDENCE_WINDOW_STARTED 2>/dev/null)"
  echo "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=$(docker compose exec -T api printenv PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED 2>/dev/null)"
} > "${SNAPSHOT_DIR}/runtime_phase5_flags.txt"
FLAGS_EXIT=$?
set -e

STATUS="passed"
if [ "${HEALTH_EXIT}" -ne 0 ] || [ "${REPORT_EXIT}" -ne 0 ] || [ "${COMPOSE_PS_EXIT}" -ne 0 ] || [ "${LOGS_EXIT}" -ne 0 ] || [ "${FLAGS_EXIT}" -ne 0 ]; then
  STATUS="failed"
fi

cat > "${SNAPSHOT_DIR}/snapshot_manifest.json" <<EOF
{
  "snapshot_id": "${SNAPSHOT_ID}",
  "generated_at": "${GENERATED_AT}",
  "window_start_utc": "${PHASE5_WINDOW_START_UTC}",
  "window_end_utc": "${PHASE5_WINDOW_END_UTC}",
  "api_base_url": "${PHASE5_API_BASE_URL}",
  "status": "${STATUS}",
  "health_exit": ${HEALTH_EXIT},
  "gray_release_report_exit": ${REPORT_EXIT},
  "docker_compose_ps_exit": ${COMPOSE_PS_EXIT},
  "service_logs_exit": ${LOGS_EXIT},
  "runtime_flags_exit": ${FLAGS_EXIT},
  "operator_review": "automated snapshot; manual review may be completed later as catch-up review"
}
EOF

echo "Phase 5 automated daily snapshot written to ${SNAPSHOT_DIR}"
if [ "${STATUS}" != "passed" ]; then
  exit 1
fi
