from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PHASE5_INFRA = REPO_ROOT / "infra" / "phase5"


def test_phase5_gray_release_scripts_capture_daily_audit_evidence() -> None:
    daily_script = PHASE5_INFRA / "write_gray_release_daily_snapshot.sh"

    content = daily_script.read_text(encoding="utf-8")

    assert "set -euo pipefail" in content
    assert 'date -u +"%Y-%m-%dT%H:%M:%SZ"' in content
    assert "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}" in content
    assert "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}" in content
    assert "${PHASE5_API_BASE_URL:-http://127.0.0.1:8000}" in content
    assert "api/v1/health" in content
    assert "api/v1/live/gray-release-report" in content
    assert "Authorization: Bearer" in content
    assert "api/v1/auth/login" in content
    assert "docker compose ps" in content
    assert "docker compose logs" in content
    assert "PHASE5_OBSERVATION_COLLECTION_ENABLED" in content
    assert "PHASE5_EVIDENCE_WINDOW_STARTED" in content
    assert "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED" in content
    assert "snapshot_manifest.json" in content


def test_phase5_gray_release_start_and_final_scripts_are_utc_bounded() -> None:
    start_script = (PHASE5_INFRA / "start_gray_release_window.sh").read_text(encoding="utf-8")
    final_script = (PHASE5_INFRA / "finalize_gray_release_window.sh").read_text(encoding="utf-8")

    assert "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}" in start_script
    assert "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}" in start_script
    assert "PHASE5_OBSERVATION_COLLECTION_ENABLED=true" in start_script
    assert "PHASE5_EVIDENCE_WINDOW_STARTED=true" in start_script
    assert "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false" in start_script
    assert 'PHASE5_COMPOSE_SERVICES="${PHASE5_COMPOSE_SERVICES:-postgres redis api worker beat}"' in start_script
    assert "docker compose up -d ${PHASE5_COMPOSE_SERVICES}" in start_script
    assert '"compose_services": "${PHASE5_COMPOSE_SERVICES}"' in start_script
    assert "window_manifest.json" in start_script

    assert "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}" in final_script
    assert "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}" in final_script
    assert "final_gray_release_report.json" in final_script
    assert "daily_snapshot_count" in final_script
    assert "closeout_manifest.json" in final_script
    assert "Authorization: Bearer" in final_script


def test_phase5_gray_release_cron_installer_documents_automated_daily_review() -> None:
    cron_script = (PHASE5_INFRA / "install_gray_release_cron.sh").read_text(encoding="utf-8")

    assert "CRON_TZ=UTC" in cron_script
    assert "write_gray_release_daily_snapshot.sh" in cron_script
    assert "PHASE5_WINDOW_START_UTC" in cron_script
    assert "PHASE5_WINDOW_END_UTC" in cron_script
    assert "phase5-gray-release-daily" in cron_script
    assert "crontab" in cron_script


def test_phase5_local_wsl_preflight_checks_required_runtime_dependencies() -> None:
    preflight_script = (PHASE5_INFRA / "preflight_local_wsl_gray_release.sh").read_text(encoding="utf-8")

    assert "set -euo pipefail" in preflight_script
    assert "command -v tmux" in preflight_script
    assert "docker version" in preflight_script
    assert "docker compose version" in preflight_script
    assert "docker compose config --quiet" in preflight_script
    assert "IBKR_PAPER_SANDBOX_HOST" in preflight_script
    assert "IBKR_PAPER_SANDBOX_PORT" in preflight_script
    assert "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED must remain false" in preflight_script
    assert "preflight_ok=true" in preflight_script


def test_phase5_local_wsl_tmux_starter_runs_formal_minimal_stack_and_snapshot_loop() -> None:
    starter_script = (PHASE5_INFRA / "start_local_wsl_tmux_gray_release.sh").read_text(encoding="utf-8")
    loop_script = (PHASE5_INFRA / "run_gray_release_daily_snapshot_loop.sh").read_text(encoding="utf-8")

    assert "${PHASE5_WINDOW_START_UTC:?PHASE5_WINDOW_START_UTC is required}" in starter_script
    assert "${PHASE5_WINDOW_END_UTC:?PHASE5_WINDOW_END_UTC is required}" in starter_script
    assert 'PHASE5_COMPOSE_SERVICES="${PHASE5_COMPOSE_SERVICES:-postgres redis api worker beat}"' in starter_script
    assert "preflight_local_wsl_gray_release.sh" in starter_script
    assert "tmux new-session" in starter_script
    assert "tmux new-window" in starter_script
    assert "start_gray_release_window.sh" in starter_script
    assert "run_gray_release_daily_snapshot_loop.sh" in starter_script
    assert "docker compose logs -f api worker beat" in starter_script
    assert "PHASE5_ADMIN_USERNAME" in starter_script

    assert "set -euo pipefail" in loop_script
    assert "write_gray_release_daily_snapshot.sh" in loop_script
    assert "sleep \"${PHASE5_DAILY_SNAPSHOT_INTERVAL_SECONDS}\"" in loop_script
    assert "PHASE5_DAILY_SNAPSHOT_INTERVAL_SECONDS=\"${PHASE5_DAILY_SNAPSHOT_INTERVAL_SECONDS:-86400}\"" in loop_script


def test_phase5_gray_release_runbook_allows_automated_daily_snapshots_with_later_review() -> None:
    runbook = REPO_ROOT / "docs" / "operations" / "paper_observation.md"

    content = runbook.read_text(encoding="utf-8")
    lower_content = content.lower()

    assert "infra/phase5/start_gray_release_window.sh" in content
    assert "infra/phase5/write_gray_release_daily_snapshot.sh" in content
    assert "infra/phase5/install_gray_release_cron.sh" in content
    assert "infra/phase5/finalize_gray_release_window.sh" in content
    assert "automated daily snapshot" in lower_content
    assert "missed manual review" in lower_content
    assert "cannot prove continuous availability" in lower_content
    assert "catch-up review" in lower_content
    assert "PHASE5_COMPOSE_SERVICES" in content
    assert "postgres redis api worker beat" in content
    assert "enough memory" in lower_content
    assert "start_local_wsl_tmux_gray_release.sh" in content
    assert "preflight_local_wsl_gray_release.sh" in content
    assert "Windows GUI" in content
    assert "tmux" in content


def test_phase5_api_container_includes_ibkr_runtime_dependency() -> None:
    pyproject = REPO_ROOT / "apps" / "api" / "pyproject.toml"

    content = pyproject.read_text(encoding="utf-8")

    assert '"ibapi==9.81.1.post1"' in content
