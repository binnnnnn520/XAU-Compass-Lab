from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_ci_workflow_runs_api_and_web_regressions() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    content = workflow.read_text(encoding="utf-8")

    assert "pull_request:" in content
    assert "postgres:" in content
    assert "python-version: \"3.13\"" in content
    assert "python -m pytest apps/api/tests/ -p no:cacheprovider" in content
    assert "npm --prefix apps/web run test" in content
    assert "npm --prefix apps/web run build" in content
    assert "DATABASE_URL:" in content
    assert "127.0.0.1:5432" in content


def test_cd_workflow_is_tag_triggered_and_packages_artifacts() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "cd.yml"

    content = workflow.read_text(encoding="utf-8")

    assert "push:" in content
    assert "tags:" in content
    assert "branches:" not in content
    assert "python -m build apps/api --outdir dist/api" in content
    assert "npm --prefix apps/web run build" in content
    assert "actions/upload-artifact" in content
    assert "python -m pytest" not in content


def test_cd_workflow_publishes_api_and_web_images_to_ghcr_with_github_token() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "cd.yml"

    content = workflow.read_text(encoding="utf-8")

    assert "packages: write" in content
    assert "docker/login-action" in content
    assert "registry: ghcr.io" in content
    assert "password: ${{ github.token }}" in content
    assert "docker/build-push-action" in content
    assert "file: infra/docker/api.Dockerfile" in content
    assert "file: infra/docker/web.Dockerfile" in content
    assert "ghcr.io/${{ github.repository }}/api:${{ github.ref_name }}" in content
    assert "ghcr.io/${{ github.repository }}/web:${{ github.ref_name }}" in content


def test_cd_workflow_does_not_require_phase5_live_trading_credentials() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "cd.yml"

    content = workflow.read_text(encoding="utf-8")
    lower_content = content.lower()

    assert "secrets." not in content
    assert "environment:" not in content
    for forbidden in (
        "broker",
        "live_trading",
        "live-trading",
        "mt5",
        "oanda",
        "alpaca",
        "binance",
        "deploy",
    ):
        assert forbidden not in lower_content
