from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

from app.middleware.request_id import REQUEST_ID_HEADER, get_request_id


Send = Callable[[dict[str, Any]], Awaitable[None]]
Receive = Callable[[], Awaitable[dict[str, Any]]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


logger = logging.getLogger("app.request")


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "UNKNOWN"))
        path = str(scope.get("path", "unknown"))
        status_code = 500
        request_id = get_request_id()
        started_at = perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal request_id, status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", status_code))
                headers = message.get("headers") or []
                for raw_name, raw_value in headers:
                    if raw_name.decode("latin-1").lower() == REQUEST_ID_HEADER.lower():
                        request_id = raw_value.decode("latin-1")
                        break
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "HTTP request completed",
                extra={
                    "request_id": request_id or "-",
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                },
            )
