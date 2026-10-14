from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Any


Send = Callable[[dict[str, Any]], Awaitable[None]]
Receive = Callable[[], Awaitable[dict[str, Any]]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


@dataclass
class RequestMetric:
    count: int = 0
    duration_sum: float = 0.0


_metrics_lock = Lock()
_request_metrics: dict[tuple[str, str, str], RequestMetric] = defaultdict(RequestMetric)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(method: str, path: str, status_code: str) -> str:
    return (
        f'method="{_escape_label(method)}",'
        f'path="{_escape_label(path)}",'
        f'status_code="{_escape_label(status_code)}"'
    )


def record_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    key = (method, path, str(status_code))
    with _metrics_lock:
        metric = _request_metrics[key]
        metric.count += 1
        metric.duration_sum += duration_seconds


def reset_metrics_for_tests() -> None:
    with _metrics_lock:
        _request_metrics.clear()


def render_metrics() -> str:
    with _metrics_lock:
        snapshot = sorted(_request_metrics.items())

    lines = [
        "# HELP api_request_total Total HTTP requests by method, path, and status.",
        "# TYPE api_request_total counter",
    ]
    for (method, path, status_code), metric in snapshot:
        lines.append(f"api_request_total{{{_labels(method, path, status_code)}}} {metric.count}")

    lines.extend(
        [
            "# HELP api_request_duration_seconds HTTP request duration by method, path, and status.",
            "# TYPE api_request_duration_seconds summary",
        ]
    )
    for (method, path, status_code), metric in snapshot:
        labels = _labels(method, path, status_code)
        lines.append(f"api_request_duration_seconds_count{{{labels}}} {metric.count}")
        lines.append(f"api_request_duration_seconds_sum{{{labels}}} {metric.duration_sum:.9f}")

    return "\n".join(lines) + "\n"


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "UNKNOWN"))
        raw_path = str(scope.get("path", "unknown"))
        status_code = 500
        started_at = perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", status_code))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            path = str(getattr(route, "path", raw_path))
            record_request(method, path, status_code, perf_counter() - started_at)
