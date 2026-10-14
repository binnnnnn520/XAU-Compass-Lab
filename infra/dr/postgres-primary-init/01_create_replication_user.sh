#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DR_REPLICATION_USER}') THEN
    CREATE ROLE ${DR_REPLICATION_USER} WITH REPLICATION LOGIN PASSWORD '${DR_REPLICATION_PASSWORD}';
  END IF;
END
\$\$;
SQL

echo "host replication ${DR_REPLICATION_USER} 0.0.0.0/0 scram-sha-256" >> "$PGDATA/pg_hba.conf"
echo "host replication ${DR_REPLICATION_USER} ::/0 scram-sha-256" >> "$PGDATA/pg_hba.conf"
