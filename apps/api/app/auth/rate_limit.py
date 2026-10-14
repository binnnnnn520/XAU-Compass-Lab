from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from time import monotonic


@dataclass
class LoginRateLimiter:
    max_failures: int = 5
    window_seconds: int = 60
    _failures: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def _prune(self, key: str, now: float) -> list[float]:
        window_start = now - self.window_seconds
        failures = [timestamp for timestamp in self._failures[key] if timestamp >= window_start]
        self._failures[key] = failures
        return failures

    def is_limited(self, key: str) -> bool:
        return len(self._prune(key, monotonic())) >= self.max_failures

    def record_failure(self, key: str) -> bool:
        now = monotonic()
        failures = self._prune(key, now)
        failures.append(now)
        self._failures[key] = failures
        return len(failures) > self.max_failures

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)


login_rate_limiter = LoginRateLimiter()
