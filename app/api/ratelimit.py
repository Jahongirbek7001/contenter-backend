"""Fixed-window limits in Redis against guessing (promo codes, passwords, logins).

Fails open: if Redis is unavailable the request goes through, so a Redis outage never
locks customers out of payments or the admin out of the cabinet.
"""

import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, redis: Redis | None) -> None:
        self._redis = redis

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        if self._redis is None:
            return True
        try:
            count = int(await self._redis.incr(f"ratelimit:{key}"))
            if count == 1:
                await self._redis.expire(f"ratelimit:{key}", window_seconds)
        except Exception:
            logger.exception("rate limiter unavailable")
            return True
        return count <= limit


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers puts the customer's address (from nginx) here.
    return request.client.host if request.client else "unknown"


def limit_by_ip(name: str, limit: int, window_seconds: int) -> Callable[[Request], Awaitable[None]]:
    async def dependency(request: Request) -> None:
        limiter: RateLimiter | None = getattr(request.app.state, "limiter", None)
        if limiter is None:
            return
        if not await limiter.allow(f"{name}:{client_ip(request)}", limit, window_seconds):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts")

    return dependency
