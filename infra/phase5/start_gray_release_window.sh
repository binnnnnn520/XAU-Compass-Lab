#!/usr/bin/env bash
set -euo pipefail

: "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}"
: "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}"

PHASE5_EVIDENCE_DIR="${PHASE5_EVIDENCE_DIR:-./evidence/phase5-gray-release}"
PHASE5_API_BASE_URL="${PHASE5_API_BASE_URL:-http://127.0.0.1:8000}"
PHASE5_COMPOSE_SERVICES="${PHASE5_COMPOSE_SERVICES:-postgres redis api worker beat}"
GENERATED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

mkdir -p "${PHASE5_EVIDENCE_DIR}/daily"

export PHASE5_OBSERVATION_COLLECTION_ENABLED=true
export PHASE5_EVIDENCE_WINDOW_STARTED=true
export PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false

docker compose up -d ${PHASE5_COMPOSE_SERVICES}

curl --fail --silent --show-error \
  "${PHASE5_API_BASE_URL%/}/api/v1/health" \
  > "${PHASE5_EVIDENCE_DIR}/start_health.json"

docker compose ps > "${PHASE5_EVIDENCE_DIR}/start_docker_compose_ps.txt"

cat > "${PHASE5_EVIDENCE_DIR}/window_manifest.json" <<EOF
{
  "window_start_utc": "${PHASE5_WINDOW_START_UTC}",
  "window_end_utc": "${PHASE5_WINDOW_END_UTC}",
  "generated_at": "${GENERATED_AT}",
  "api_base_url": "${PHASE5_API_BASE_URL}",
  "compose_services": "${PHASE5_COMPOSE_SERVICES}",
  "evidence_dir": "${PHASE5_EVIDENCE_DIR}",
  "phase5_observation_collection_enabled": "true",
  "phase5_evidence_window_started": "true",
  "phase5_ibkr_paper_order_execution_enabled": "false",
  "daily_snapshot_script": "infra/phase5/write_gray_release_daily_snapshot.sh"
}
EOF

echo "Phase 5 gray-release window start evidence written to ${PHASE5_EVIDENCE_DIR}"
