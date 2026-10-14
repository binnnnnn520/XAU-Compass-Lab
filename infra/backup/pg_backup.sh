#!/usr/bin/env bash
set -euo pipefail

DATABASE_URL="${DATABASE_URL:?DATABASE_URL is required}"
BACKUP_DIR="${BACKUP_DIR:-./backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUTPUT_FILE="${BACKUP_DIR}/gold_agent_${TIMESTAMP}.dump"

mkdir -p "${BACKUP_DIR}"

pg_dump "${DATABASE_URL}" \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file "${OUTPUT_FILE}"

if [ "${RETENTION_DAYS}" -gt 0 ] 2>/dev/null; then
  find "${BACKUP_DIR}" -name "gold_agent_*.dump" -type f -mtime "+${RETENTION_DAYS}" -delete
fi

printf '%s\n' "${OUTPUT_FILE}"
