"""In-process sliding-window rate limiter.

Deliberately dependency-free so local dev needs no Redis. Swap `_Backend` for a
Redis implementation when you run more than one worker process — the call sites
(`RateLimit(...)` dependencies) do not change.
"""

# NOTE: deliberately no `from __future__ import annotations`.
# `RateLimit` is used as a *callable instance* dependency, and FastAPI resolves a
# callable object's annotations without a `__globals__` to look names up in — a
# stringified `Request` annotation would be mistaken for a query parameter.

import asyncio
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import settings
from app.core.errors import RateLimitError

_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_rate(rate: str) -> tuple[int, int]:
    """'300/minute' → (300, 60)"""
    count, _, unit = rate.partition("/")
    return int(count), _UNITS.get(unit.strip().rstrip("s"), 60)


class _Backend:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._last_sweep = time.monotonic()

    async def check(self, key: str, limit: int, window: int) -> tuple[bool, int, int]:
        now = time.monotonic()
        async with self._lock:
            if now - self._last_sweep > 300:
                self._sweep(now)
            bucket = self._hits[key]
            cutoff = now - window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = int(bucket[0] + window - now) + 1
                return False, 0, retry_after
            bucket.append(now)
            return True, limit - len(bucket), 0

    def _sweep(self, now: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] > 3600]
        for k in stale:
            del self._hits[k]
        self._last_sweep = now


_backend = _Backend()


def client_key(request: Request) -> str:
    """Prefer the authenticated user; fall back to a proxy-aware IP."""
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


class RateLimit:
    """FastAPI dependency: `Depends(RateLimit(settings.RATE_LIMIT_AI, scope='ai'))`."""

    def __init__(self, rate: str | None = None, scope: str = "default") -> None:
        self.limit, self.window = parse_rate(rate or settings.RATE_LIMIT_DEFAULT)
        self.scope = scope

    async def __call__(self, request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED or settings.ENVIRONMENT == "test":
            return
        key = f"{self.scope}:{client_key(request)}"
        allowed, remaining, retry_after = await _backend.check(key, self.limit, self.window)
        request.state.rate_limit_remaining = remaining
        if not allowed:
            raise RateLimitError(
                "Too many requests. Please try again shortly.",
                details={"retry_after_seconds": retry_after, "limit": self.limit, "scope": self.scope},
            )


default_limit = RateLimit(settings.RATE_LIMIT_DEFAULT, "default")
auth_limit = RateLimit(settings.RATE_LIMIT_AUTH, "auth")
ai_limit = RateLimit(settings.RATE_LIMIT_AI, "ai")
