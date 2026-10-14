from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.config import get_settings
from app.schemas import HealthData


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def check_tcp_connectivity(host: str, port: int, timeout: float) -> bool:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError):
        return False

    writer.close()
    await writer.wait_closed()
    return True


async def get_health_data() -> HealthData:
    settings = get_settings()
    db_connected, redis_connected = await asyncio.gather(
        check_tcp_connectivity(
            settings.database_host,
            settings.database_port,
            settings.connect_timeout_seconds,
        ),
        check_tcp_connectivity(
            settings.redis_host,
            settings.redis_port,
            settings.connect_timeout_seconds,
        ),
    )

    status = "healthy" if db_connected and redis_connected else "degraded"
    return HealthData(
        status=status,
        version=settings.app_version,
        db_connected=db_connected,
        redis_connected=redis_connected,
        timestamp=utc_timestamp(),
    )
