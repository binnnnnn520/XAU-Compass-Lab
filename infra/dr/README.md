# Isolated Recovery Rehearsal

This directory defines an isolated DR stack for exploring PostgreSQL and Redis recovery. It is separate from the application Compose file and must not share volumes, database names, or container names with the application stack.

Components:

- PostgreSQL streaming replication with a primary and hot standby replica.
- Redis Sentinel monitoring a Redis master plus replica.

Measure recovery time (RTO) and recoverable data age (RPO) for your own workload. The verifier's printed RTO/RPO thresholds are reference labels, not measured results and not an availability guarantee.

This is an isolated DR stack. Do not point this stack at production, do not reuse production credentials, and do
not run restore or failover rehearsals against production data.

## Start

From the repository root:

```powershell
$env:DR_POSTGRES_PASSWORD="change_me_dr_postgres_password"
$env:DR_REPLICATION_PASSWORD="change_me_dr_replication_password"
$env:DR_REDIS_PASSWORD="change_me_dr_redis_password"
docker compose -f infra/dr/docker-compose.phase5-dr.yml up -d
```

## Verify

```powershell
.\infra\dr\verify_phase5_dr.ps1
```

The verification checks:

- the PostgreSQL replica returns `pg_is_in_recovery() = true`;
- Redis Sentinel resolves `gold-agent-dr-redis` to the Redis master;
- diagnostic output is available for recording alongside measured recovery time and data loss.

## Stop

```powershell
docker compose -f infra/dr/docker-compose.phase5-dr.yml down
```

Use `down -v` only for disposable local evidence runs where deleting isolated DR volumes is intentional.
