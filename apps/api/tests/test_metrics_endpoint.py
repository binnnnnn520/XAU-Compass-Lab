from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import httpx


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.main import app
from app.middleware.metrics import reset_metrics_for_tests


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def test_metrics_endpoint_exposes_prometheus_text_format() -> None:
    response = asyncio.run(_get("/metrics"))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP api_request_total" in response.text
    assert "# TYPE api_request_total counter" in response.text


def test_metrics_middleware_records_http_requests() -> None:
    reset_metrics_for_tests()

    response = asyncio.run(_get("/api/v1/does-not-exist"))
    metrics = asyncio.run(_get("/metrics"))

    assert response.status_code == 404
    assert 'api_request_total{method="GET",path="/api/v1/does-not-exist",status_code="404"} 1' in metrics.text
    assert 'api_request_duration_seconds_count{method="GET",path="/api/v1/does-not-exist",status_code="404"} 1' in metrics.text
