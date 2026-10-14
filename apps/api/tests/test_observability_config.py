from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_text(path: Path) -> str:
    assert path.exists(), f"missing expected observability config: {path}"
    return path.read_text(encoding="utf-8")


def _load_dashboard(name: str) -> dict:
    dashboard_path = REPO_ROOT / "infra" / "grafana" / "dashboards" / name
    assert dashboard_path.exists(), f"missing expected dashboard: {dashboard_path}"
    return json.loads(dashboard_path.read_text(encoding="utf-8"))


def _dashboard_exprs(dashboard: dict) -> list[str]:
    return [
        target.get("expr", "")
        for panel in dashboard.get("panels", [])
        for target in panel.get("targets", [])
    ]


def test_prometheus_scrapes_api_metrics_endpoint() -> None:
    content = _read_text(REPO_ROOT / "infra" / "prometheus" / "prometheus.yml")

    assert "scrape_configs:" in content
    assert "job_name: api" in content or "job_name: \"api\"" in content
    assert "metrics_path: /metrics" in content
    assert "api:8000" in content


def test_grafana_datasource_points_to_prometheus() -> None:
    content = _read_text(
        REPO_ROOT
        / "infra"
        / "grafana"
        / "provisioning"
        / "datasources"
        / "prometheus.yml"
    )

    assert "apiVersion: 1" in content
    assert "name: Prometheus" in content
    assert "type: prometheus" in content
    assert "access: proxy" in content
    assert "url: http://prometheus:9090" in content


def test_grafana_dashboard_provider_loads_dashboard_directory() -> None:
    content = _read_text(
        REPO_ROOT
        / "infra"
        / "grafana"
        / "provisioning"
        / "dashboards"
        / "dashboard.yml"
    )

    assert "apiVersion: 1" in content
    assert "name: gold-agent-dashboards" in content
    assert "folder: Gold Agent" in content
    assert "path: /var/lib/grafana/dashboards" in content


def test_api_dashboard_contains_request_count_and_latency_panels() -> None:
    dashboard = _load_dashboard("api_overview.json")
    panel_exprs = _dashboard_exprs(dashboard)
    dashboard_expr_text = "\n".join(panel_exprs)

    assert any("api_request_total" in expr for expr in panel_exprs)
    assert any("api_request_duration_seconds" in expr for expr in panel_exprs)
    assert "api_request_duration_seconds_bucket" not in dashboard_expr_text
    assert "api_request_duration_seconds_sum" in dashboard_expr_text
    assert "api_request_duration_seconds_count" in dashboard_expr_text


def test_trading_signals_dashboard_contains_business_metric_panels() -> None:
    dashboard = _load_dashboard("trading_signals.json")
    panel_exprs = _dashboard_exprs(dashboard)

    assert dashboard.get("timezone") == "utc"
    assert dashboard.get("panels")
    assert any("signal_generated_total" in expr for expr in panel_exprs)
    assert any("model_prediction_confidence" in expr for expr in panel_exprs)
    assert any("paper_account_equity" in expr for expr in panel_exprs)


def test_risk_monitoring_dashboard_contains_business_metric_panels() -> None:
    dashboard = _load_dashboard("risk_monitoring.json")
    panel_exprs = _dashboard_exprs(dashboard)

    assert dashboard.get("timezone") == "utc"
    assert dashboard.get("panels")
    assert any("risk_rejection_total" in expr for expr in panel_exprs)
    assert any("active_positions_count" in expr for expr in panel_exprs)
    assert any("paper_account_equity" in expr for expr in panel_exprs)


def test_compose_defines_prometheus_and_grafana_services() -> None:
    content = _read_text(REPO_ROOT / "docker-compose.yml")

    assert "  prometheus:" in content
    assert "image: prom/prometheus:" in content
    assert "./infra/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro" in content
    assert "  grafana:" in content
    assert "image: grafana/grafana:" in content
    assert "./infra/grafana/provisioning:/etc/grafana/provisioning:ro" in content
    assert "./infra/grafana/dashboards:/var/lib/grafana/dashboards:ro" in content
