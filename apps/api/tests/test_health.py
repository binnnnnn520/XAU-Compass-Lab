from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from app.main import app
from app.schemas import HealthData


async def get_health_response() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get("/api/v1/health")


def test_health_returns_unified_envelope(monkeypatch) -> None:
    async def fake_health_data() -> HealthData:
        return HealthData(
            status="healthy",
            version="0.1.0",
            db_connected=True,
            redis_connected=True,
            timestamp="2026-03-31T14:00:00Z",
        )

    monkeypatch.setattr("app.routes.health.get_health_data", fake_health_data)

    response = asyncio.run(get_health_response())

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"] == {
        "status": "healthy",
        "version": "0.1.0",
        "db_connected": True,
        "redis_connected": True,
        "timestamp": "2026-03-31T14:00:00Z",
    }


def test_health_timestamp_is_utc(monkeypatch) -> None:
    async def fake_health_data() -> HealthData:
        return HealthData(
            status="healthy",
            version="0.1.0",
            db_connected=True,
            redis_connected=True,
            timestamp="2026-03-31T14:00:00Z",
        )

    monkeypatch.setattr("app.routes.health.get_health_data", fake_health_data)

    response = asyncio.run(get_health_response())

    timestamp = response.json()["data"]["timestamp"]
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert parsed.tzinfo == UTC
