from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import sys

import httpx


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.logging_config import JsonLogFormatter, RequestIdFilter
from app.main import app
from app.middleware.request_id import REQUEST_ID_HEADER
from app.schemas import HealthData


async def _boom_endpoint():
    raise RuntimeError("synthetic request id failure")


app.add_api_route("/api/v1/_test_request_id_500", _boom_endpoint, methods=["GET"])


async def _request(
    headers: dict[str, str] | None = None,
    *,
    path: str = "/api/v1/does-not-exist",
    raise_app_exceptions: bool = True,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, headers=headers)


def test_request_id_middleware_echoes_existing_header() -> None:
    response = asyncio.run(_request({REQUEST_ID_HEADER: "round3-test-request"}))

    assert response.status_code == 404
    assert response.headers[REQUEST_ID_HEADER] == "round3-test-request"
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_request_id_middleware_generates_missing_header() -> None:
    response = asyncio.run(_request())

    assert response.status_code == 404
    assert response.headers[REQUEST_ID_HEADER]
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_request_id_filter_preserves_explicit_request_id() -> None:
    record = logging.LogRecord(
        name="app.main",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="synthetic",
        args=(),
        exc_info=None,
    )
    record.request_id = "explicit-request-id"

    RequestIdFilter().filter(record)

    assert record.request_id == "explicit-request-id"


def test_runtime_request_log_includes_request_id(monkeypatch, caplog) -> None:
    async def fake_health_data() -> HealthData:
        return HealthData(
            status="healthy",
            version="test",
            db_connected=True,
            redis_connected=True,
            timestamp="2026-04-30T00:00:00Z",
        )

    monkeypatch.setattr("app.routes.health.get_health_data", fake_health_data)
    request_logger = logging.getLogger("app.request")
    request_logger.disabled = False
    caplog.set_level(logging.INFO, logger=request_logger.name)

    response = asyncio.run(_request({REQUEST_ID_HEADER: "phase3-log-request"}, path="/api/v1/health"))

    assert response.status_code == 200
    records = [record for record in caplog.records if record.name == request_logger.name]
    assert len(records) == 1

    payload = json.loads(JsonLogFormatter().format(records[0]))
    assert payload["request_id"] == "phase3-log-request"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/health"
    assert payload["status_code"] == 200


def test_request_id_middleware_preserves_header_on_unhandled_error(monkeypatch) -> None:
    logged: dict[str, object] = {}

    def fake_exception(message, *args, **kwargs) -> None:
        logged["message"] = message
        logged["extra"] = kwargs.get("extra")

    monkeypatch.setattr("app.main.logger.exception", fake_exception)

    response = asyncio.run(
        _request(
            {REQUEST_ID_HEADER: "round3-500-request"},
            path="/api/v1/_test_request_id_500",
            raise_app_exceptions=False,
        )
    )

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "round3-500-request"
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert logged["extra"] == {"request_id": "round3-500-request"}
