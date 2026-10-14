# PostgreSQL Backup And Restore Rehearsal

These scripts provide the Phase 3 PostgreSQL backup baseline for the MVP
production upgrade. They are for backup creation and restore rehearsal only.

## Create A Backup

Use a libpq PostgreSQL URL, not a SQLAlchemy driver URL:

```bash
export POSTGRES_PASSWORD="change_me_postgres_password"
export DATABASE_URL="postgresql://gold_agent:${POSTGRES_PASSWORD}@127.0.0.1:5432/gold_agent"
export BACKUP_DIR="./backups/postgres"
./pg_backup.sh
```

The backup file name uses a UTC timestamp, for example:

```text
./backups/postgres/gold_agent_20260430T120000Z.dump
```

## Restore Rehearsal

Run every restore rehearsal against an isolated database. Do not run restore rehearsals against production.
Do not point `DATABASE_URL` at the primary application database while rehearsing.

Example isolated database flow:

```bash
createdb gold_agent_restore_rehearsal

export POSTGRES_PASSWORD="change_me_postgres_password"
export DATABASE_URL="postgresql://gold_agent:${POSTGRES_PASSWORD}@127.0.0.1:5432/gold_agent_restore_rehearsal"
./pg_restore.sh ./backups/postgres/gold_agent_20260430T120000Z.dump

psql "$DATABASE_URL" -c "select version_num from alembic_version;"

dropdb gold_agent_restore_rehearsal
```

Use a fresh isolated database name for repeated rehearsals if the previous run
needs to be retained for inspection. The restore script uses `pg_restore
--clean --if-exists`, so it can reset objects inside the isolated target, but
that behavior is the reason production databases must never be used for a
rehearsal.

## Required Inputs

- `DATABASE_URL`: required target database URL.
- `POSTGRES_PASSWORD`: example helper variable for constructing a libpq URL without embedding a literal password in shell history snippets.
- `BACKUP_DIR`: optional backup output directory for `pg_backup.sh`; defaults to
  `./backups/postgres`.
- `RETENTION_DAYS`: optional retention window for `pg_backup.sh`; defaults to
  `14`.
