from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.logging_config import configure_logging
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.metrics import MetricsMiddleware, render_metrics
from app.middleware.request_id import REQUEST_ID_HEADER, RequestIdMiddleware, get_request_id
from app.routes.auth import router as auth_router
from app.routes.backtest import router as backtest_router
from app.routes.core_api import router as core_api_router
from app.routes.health import router as health_router
from app.routes.live import router as live_router
from app.routes.paper import router as paper_router
from app.routes.websocket import router as websocket_router
from app.schemas import ApiException, error_response


logger = logging.getLogger(__name__)
configure_logging()
settings = get_settings()

app = FastAPI(title="Gold Agent API", version=settings.app_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(MetricsMiddleware)


def _request_id_for(request: Request) -> str | None:
    return getattr(request.state, "request_id", None) or get_request_id()


def _with_request_id(request: Request, response: JSONResponse) -> JSONResponse:
    request_id = _request_id_for(request)
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    return Response(render_metrics(), media_type="text/plain; version=0.0.4")


@app.exception_handler(ApiException)
async def handle_api_exception(request: Request, exc: ApiException):
    return _with_request_id(
        request,
        error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            detail=exc.detail,
        ),
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_exception(request: Request, exc: RequestValidationError):
    return _with_request_id(
        request,
        error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            detail=exc.errors(),
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return _with_request_id(
            request,
            error_response(
                status_code=exc.status_code,
                code="NOT_FOUND",
                message="Resource not found.",
                detail={"path": str(request.url.path)},
            ),
        )
    if exc.status_code in {
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_405_METHOD_NOT_ALLOWED,
    }:
        return _with_request_id(
            request,
            error_response(
                status_code=exc.status_code,
                code="VALIDATION_ERROR",
                message=str(exc.detail),
            ),
        )
    if exc.status_code == status.HTTP_409_CONFLICT:
        return _with_request_id(
            request,
            error_response(
                status_code=exc.status_code,
                code="CONFLICT",
                message=str(exc.detail),
            ),
        )
    if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return _with_request_id(
            request,
            error_response(
                status_code=exc.status_code,
                code="RATE_LIMITED",
                message=str(exc.detail),
            ),
        )
    if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        return _with_request_id(
            request,
            error_response(
                status_code=exc.status_code,
                code="SERVICE_UNAVAILABLE",
                message=str(exc.detail),
            ),
        )
    return _with_request_id(
        request,
        error_response(
            status_code=exc.status_code,
            code="VALIDATION_ERROR" if exc.status_code < 500 else "INTERNAL_ERROR",
            message=str(exc.detail),
        ),
    )


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception):
    request_id = _request_id_for(request)
    logger.exception("Unhandled API exception for %s", request.url.path, exc_info=exc, extra={"request_id": request_id})
    return _with_request_id(
        request,
        error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="An internal server error occurred.",
        ),
    )


app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(core_api_router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(paper_router, prefix="/api/v1")
app.include_router(live_router, prefix="/api/v1")
app.include_router(websocket_router, prefix="/api/v1")
