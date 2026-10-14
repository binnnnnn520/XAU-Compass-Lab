param(
    [string]$PostgresUser = $(if ($env:DR_POSTGRES_USER) { $env:DR_POSTGRES_USER } else { "gold_agent" }),
    [string]$PostgresDb = $(if ($env:DR_POSTGRES_DB) { $env:DR_POSTGRES_DB } else { "gold_agent_dr" }),
    [string]$RedisPassword = $env:DR_REDIS_PASSWORD
)

$ErrorActionPreference = "Stop"

if (-not $env:DR_POSTGRES_PASSWORD) {
    throw "DR_POSTGRES_PASSWORD is required for the isolated DR verification."
}
if (-not $RedisPassword) {
    throw "DR_REDIS_PASSWORD is required for the isolated DR verification."
}

$replicaRecovery = docker exec `
    -e PGPASSWORD=$env:DR_POSTGRES_PASSWORD `
    gold-agent-dr-postgres-replica `
    psql -U $PostgresUser -d $PostgresDb -tA -c "select pg_is_in_recovery();"

if (($replicaRecovery | Select-Object -First 1).Trim() -ne "t") {
    throw "PostgreSQL replica is not in recovery mode."
}

$sentinelMaster = docker exec gold-agent-dr-redis-sentinel-1 `
    redis-cli -p 26379 SENTINEL get-master-addr-by-name gold-agent-dr-redis

if (($sentinelMaster | Measure-Object).Count -lt 2 -or (($sentinelMaster | Select-Object -Last 1).Trim() -ne "6379")) {
    throw "Redis Sentinel did not report a valid master endpoint for gold-agent-dr-redis."
}

[pscustomobject]@{
    postgres_replica_in_recovery = $true
    redis_sentinel_master        = ($sentinelMaster -join " ")
    rto_target                   = "RTO < 1 hour"
    rpo_target                   = "RPO < 1 hour"
} | ConvertTo-Json -Depth 3
