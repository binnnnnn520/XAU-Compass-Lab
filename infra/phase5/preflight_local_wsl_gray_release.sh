#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PHASE5_COMPOSE_SERVICES="${PHASE5_COMPOSE_SERVICES:-postgres redis api worker beat}"

fail() {
  echo "preflight_failed=$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing_$1"
}

cd "${REPO_ROOT}"

command -v tmux >/dev/null 2>&1 || fail "missing_tmux"
require_command docker

docker version >/dev/null || fail "docker_engine_unavailable"
docker compose version >/dev/null || fail "docker_compose_unavailable"

test -f .env || fail "env_missing"

set -a
# shellcheck disable=SC1091
. ./.env
set +a

REQUIRED_ENV_VARS=(
  DATABASE_URL
  POSTGRES_PASSWORD
  REDIS_PASSWORD
  GRAFANA_ADMIN_PASSWORD
  IBKR_PAPER_SANDBOX_MODE
  IBKR_PAPER_SANDBOX_HOST
  IBKR_PAPER_SANDBOX_PORT
  IBKR_PAPER_SANDBOX_CLIENT_ID
  IBKR_PAPER_SANDBOX_ACCOUNT_ID
)

for var_name in "${REQUIRED_ENV_VARS[@]}"; do
  if [ -z "${!var_name:-}" ]; then
    fail "missing_${var_name}"
  fi
done

if [ "${PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED:-false}" = "true" ]; then
  echo "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED must remain false for the gray-release window." >&2
  exit 1
fi

if [ "${IBKR_PAPER_SANDBOX_MODE}" != "paper" ]; then
  fail "ibkr_mode_must_be_paper"
fi

if [ "${IBKR_PAPER_SANDBOX_HOST}" != "host.docker.internal" ]; then
  fail "ibkr_host_must_be_host_docker_internal_for_wsl"
fi

if command -v timeout >/dev/null 2>&1; then
  timeout 5 bash -c "cat < /dev/null > /dev/tcp/${IBKR_PAPER_SANDBOX_HOST}/${IBKR_PAPER_SANDBOX_PORT}" \
    || fail "ibkr_paper_api_unreachable"
else
  bash -c "cat < /dev/null > /dev/tcp/${IBKR_PAPER_SANDBOX_HOST}/${IBKR_PAPER_SANDBOX_PORT}" \
    || fail "ibkr_paper_api_unreachable"
fi

docker compose config --quiet

echo "repo_root=${REPO_ROOT}"
echo "compose_services=${PHASE5_COMPOSE_SERVICES}"
echo "ibkr_endpoint=${IBKR_PAPER_SANDBOX_HOST}:${IBKR_PAPER_SANDBOX_PORT}"
echo "preflight_ok=true"
