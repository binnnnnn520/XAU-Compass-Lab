# Phase 5 DR Deployment Evidence Stack

This directory defines an isolated DR stack for Phase 5 live readiness. It is separate from the normal local
development compose file and must not share volumes, database names, or container names with the application stack.

Targets:

- RTO < 1 hour.
- RPO < 1 hour.
- PostgreSQL streaming replication with a primary and hot standby replica.
- Redis Sentinel monitoring a Redis master plus replica.

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
- RTO/RPO targets remain documented with the evidence output.

## Stop

```powershell
docker compose -f infra/dr/docker-compose.phase5-dr.yml down
```

Use `down -v` only for disposable local evidence runs where deleting isolated DR volumes is intentional.
