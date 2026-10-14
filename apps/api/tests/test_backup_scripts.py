from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_postgres_backup_script_uses_utc_timestamp_and_custom_dump() -> None:
    script = REPO_ROOT / "infra" / "backup" / "pg_backup.sh"

    content = script.read_text(encoding="utf-8")

    assert "set -euo pipefail" in content
    assert 'date -u +"%Y%m%dT%H%M%SZ"' in content
    assert "${DATABASE_URL:?DATABASE_URL is required}" in content
    assert "${BACKUP_DIR:-./backups/postgres}" in content
    assert "pg_dump" in content
    assert "--format=custom" in content
    assert "--no-owner" in content
    assert "--no-privileges" in content


def test_postgres_restore_script_requires_explicit_backup_file() -> None:
    script = REPO_ROOT / "infra" / "backup" / "pg_restore.sh"

    content = script.read_text(encoding="utf-8")

    assert "set -euo pipefail" in content
    assert "${DATABASE_URL:?DATABASE_URL is required}" in content
    assert "Usage: DATABASE_URL=... ./pg_restore.sh <backup-file>" in content
    assert "pg_restore" in content
    assert "--clean" in content
    assert "--if-exists" in content
    assert "--no-owner" in content


def test_backup_readme_documents_isolated_restore_rehearsal() -> None:
    readme = REPO_ROOT / "infra" / "backup" / "README.md"

    content = readme.read_text(encoding="utf-8")
    lower_content = content.lower()

    assert "restore rehearsal" in lower_content
    assert "isolated database" in lower_content
    assert "do not run restore rehearsals against production" in lower_content
    assert "gold_agent_restore_rehearsal" in content
    assert "createdb" in content
    assert "DATABASE_URL=" in content
    assert "./pg_restore.sh" in content
    assert 'psql "$DATABASE_URL" -c "select version_num from alembic_version;"' in content
