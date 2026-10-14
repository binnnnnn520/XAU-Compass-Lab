#!/usr/bin/env bash
set -euo pipefail

DATABASE_URL="${DATABASE_URL:?DATABASE_URL is required}"

if [ "$#" -ne 1 ]; then
  printf '%s\n' "Usage: DATABASE_URL=... ./pg_restore.sh <backup-file>" >&2
  exit 2
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
  printf 'Backup file not found: %s\n' "${BACKUP_FILE}" >&2
  exit 2
fi

pg_restore \
  --dbname "${DATABASE_URL}" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  "${BACKUP_FILE}"
