from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_compose_forwards_required_auth_secret_to_runtime_services() -> None:
    compose_content = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert compose_content.count(
        "AUTH_TOKEN_SECRET: ${AUTH_TOKEN_SECRET:?AUTH_TOKEN_SECRET is required}"
    ) == 3
    assert "AUTH_TOKEN_SECRET=change_me_auth_token_secret" in env_content


def test_open_source_example_disables_external_llm_and_defines_monitoring_password() -> None:
    env_content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "LLM_ANALYSIS_ENABLED=false" in env_content
    assert "LLM_API_KEY=\n" in env_content
    assert "GRAFANA_ADMIN_PASSWORD=change_me_grafana_password" in env_content


def test_example_env_does_not_publish_default_database_password() -> None:
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "POSTGRES_PASSWORD=gold_agent" not in content
    assert "postgresql://gold_agent:gold_agent@" not in content
    assert "change_me_postgres_password" in content


def test_example_env_requires_redis_password_placeholder() -> None:
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "REDIS_PASSWORD=change_me_redis_password" in content
    assert "REDIS_URL=redis://:change_me_redis_password@redis:6379/0" in content
    assert "REDIS_URL=redis://redis:6379/0" not in content


def test_compose_requires_database_credentials_from_environment() -> None:
    content = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "postgresql://gold_agent:gold_agent@" not in content
    assert "POSTGRES_PASSWORD:-gold_agent" not in content
    assert "${DATABASE_URL:?DATABASE_URL is required}" in content
    assert "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}" in content


def test_compose_requires_redis_password_and_uses_authenticated_urls() -> None:
    content = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    required_password = "${REDIS_PASSWORD:?REDIS_PASSWORD is required}"
    authenticated_url = (
        "redis://:${REDIS_PASSWORD:?REDIS_PASSWORD is required}@redis:6379/0"
    )

    assert required_password in content
    assert "--requirepass" in content
    assert f"REDIS_URL: ${{REDIS_URL:-{authenticated_url}}}" in content
    assert f"--broker=${{REDIS_URL:-{authenticated_url}}}" in content
    assert "redis://redis:6379/0" not in content


def test_runtime_config_does_not_embed_default_database_password() -> None:
    config_content = (REPO_ROOT / "apps/api/app/config.py").read_text(encoding="utf-8")
    database_content = (REPO_ROOT / "apps/api/app/database.py").read_text(encoding="utf-8")

    assert "postgresql://gold_agent:gold_agent@" not in config_content
    assert "postgresql://gold_agent:gold_agent@" not in database_content
    assert "postgresql://gold_agent@localhost:5432/gold_agent" in config_content
    assert "postgresql://gold_agent@localhost:5432/gold_agent" in database_content


def test_backup_readme_avoids_literal_password_examples() -> None:
    content = (REPO_ROOT / "infra/backup/README.md").read_text(encoding="utf-8")

    assert "postgresql://gold_agent:gold_agent@" not in content
    assert 'export POSTGRES_PASSWORD="change_me_postgres_password"' in content
    assert (
        'export DATABASE_URL="postgresql://gold_agent:${POSTGRES_PASSWORD}@127.0.0.1:5432/gold_agent"'
        in content
    )


def test_phase5_ibkr_paper_order_execution_is_disabled_by_default() -> None:
    env_content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    config_content = (REPO_ROOT / "apps/api/app/config.py").read_text(encoding="utf-8")

    assert "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false" in env_content
    assert "phase5_ibkr_paper_order_execution_enabled" in config_content
    assert 'os.getenv("PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED")' in config_content


def test_phase5_runtime_and_ibkr_env_are_forwarded_to_runtime_services() -> None:
    env_content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    compose_content = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "PHASE5_OBSERVATION_COLLECTION_ENABLED=false" in env_content
    assert "PHASE5_EVIDENCE_WINDOW_STARTED=false" in env_content
    assert "IBKR_PAPER_SANDBOX_MODE=paper" in env_content
    assert "IBKR_PAPER_SANDBOX_HOST=" in env_content
    assert "IBKR_PAPER_SANDBOX_PORT=" in env_content
    assert "IBKR_PAPER_SANDBOX_CLIENT_ID=" in env_content
    assert "IBKR_PAPER_SANDBOX_ACCOUNT_ID=" in env_content

    assert (
        compose_content.count(
            "PHASE5_OBSERVATION_COLLECTION_ENABLED: ${PHASE5_OBSERVATION_COLLECTION_ENABLED:-false}"
        )
        >= 3
    )
    assert (
        compose_content.count(
            "PHASE5_EVIDENCE_WINDOW_STARTED: ${PHASE5_EVIDENCE_WINDOW_STARTED:-false}"
        )
        >= 3
    )
    assert (
        compose_content.count(
            "PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED: ${PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED:-false}"
        )
        >= 3
    )
    assert (
        compose_content.count("IBKR_PAPER_SANDBOX_MODE: ${IBKR_PAPER_SANDBOX_MODE:-paper}")
        >= 3
    )
    assert (
        compose_content.count("IBKR_PAPER_SANDBOX_HOST: ${IBKR_PAPER_SANDBOX_HOST:-}")
        >= 3
    )
    assert (
        compose_content.count("IBKR_PAPER_SANDBOX_PORT: ${IBKR_PAPER_SANDBOX_PORT:-}")
        >= 3
    )
    assert (
        compose_content.count(
            "IBKR_PAPER_SANDBOX_CLIENT_ID: ${IBKR_PAPER_SANDBOX_CLIENT_ID:-}"
        )
        >= 3
    )
    assert (
        compose_content.count(
            "IBKR_PAPER_SANDBOX_ACCOUNT_ID: ${IBKR_PAPER_SANDBOX_ACCOUNT_ID:-}"
        )
        >= 3
    )


def test_phase5_runtime_services_can_reach_host_ibkr_gateway() -> None:
    compose_content = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert compose_content.count("host.docker.internal:host-gateway") >= 3
