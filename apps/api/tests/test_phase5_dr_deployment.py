from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_phase5_dr_compose_defines_postgres_streaming_replication_and_redis_sentinel() -> None:
    content = (REPO_ROOT / "infra/dr/docker-compose.phase5-dr.yml").read_text(encoding="utf-8")

    assert "gold-agent-dr-postgres-primary" in content
    assert "gold-agent-dr-postgres-replica" in content
    assert "pg_basebackup" in content
    assert "hot_standby=on" in content
    assert "${DR_POSTGRES_PASSWORD:?DR_POSTGRES_PASSWORD is required}" in content
    assert "${DR_REPLICATION_PASSWORD:?DR_REPLICATION_PASSWORD is required}" in content
    assert "gold-agent-dr-redis-master" in content
    assert "gold-agent-dr-redis-replica" in content
    assert "gold-agent-dr-redis-sentinel-1" in content
    assert "sentinel monitor gold-agent-dr-redis" in content
    assert "${DR_REDIS_PASSWORD:?DR_REDIS_PASSWORD is required}" in content


def test_phase5_dr_verification_script_checks_replica_and_sentinel_without_production_targets() -> None:
    content = (REPO_ROOT / "infra/dr/verify_phase5_dr.ps1").read_text(encoding="utf-8")

    assert "pg_is_in_recovery()" in content
    assert "SENTINEL get-master-addr-by-name gold-agent-dr-redis" in content
    assert "gold-agent-dr-postgres-replica" in content
    assert "gold-agent-dr-redis-sentinel-1" in content
    assert "gold-agent-postgres" not in content
    assert "gold-agent-redis" not in content


def test_phase5_dr_runbook_records_rto_rpo_and_isolated_stack() -> None:
    content = (REPO_ROOT / "infra/dr/README.md").read_text(encoding="utf-8")
    lower_content = content.lower()

    assert "rto < 1 hour" in lower_content
    assert "rpo < 1 hour" in lower_content
    assert "streaming replication" in lower_content
    assert "redis sentinel" in lower_content
    assert "isolated dr stack" in lower_content
    assert "do not point this stack at production" in lower_content
