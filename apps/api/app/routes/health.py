from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.schemas import ErrorPayload, HealthEnvelope
from app.services.health import get_health_data

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthEnvelope)
async def healthcheck() -> JSONResponse:
    health_data = await get_health_data()
    is_healthy = health_data.db_connected and health_data.redis_connected

    if is_healthy:
        body = HealthEnvelope(success=True, data=health_data, error=None)
        return JSONResponse(status_code=status.HTTP_200_OK, content=body.model_dump(mode="json"))

    body = HealthEnvelope(
        success=False,
        data=health_data,
        error=ErrorPayload(
            code="SERVICE_UNAVAILABLE",
            message="One or more infrastructure dependencies are unavailable.",
            detail={
                "db_connected": health_data.db_connected,
                "redis_connected": health_data.redis_connected,
            },
        ),
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body.model_dump(mode="json"),
    )

