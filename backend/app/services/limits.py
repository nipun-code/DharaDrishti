"""System guardrails (SPEC §8.4): per-user/per-IP rate limits and a daily token budget, in Redis.

Both fail open if Redis errors (availability over strictness), logging a warning.
"""

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.exceptions import RateLimitedError, TokenBudgetExceededError

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60
_BUDGET_KEY_TTL = 2 * 24 * 3600


class RateLimiter:
    """Fixed one-minute windows: at most `limit` hits per key per window."""

    def __init__(self, redis: Redis, *, now: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._now = now

    async def hit(self, key: str, limit: int) -> None:
        now = self._now()
        window = int(now // _WINDOW_SECONDS)
        redis_key = f"rl:{key}:{window}"
        try:
            await self._redis.set(redis_key, 0, ex=_WINDOW_SECONDS + 1, nx=True)
            count = int(await self._redis.incr(redis_key))
        except RedisError:
            logger.warning("rate_limit_unavailable", exc_info=True)
            return
        if count > limit:
            retry_after = max(1, int((window + 1) * _WINDOW_SECONDS - now))
            raise RateLimitedError(
                f"Too many requests: limit is {limit} per minute. Try again in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )


class TokenBudget:
    """Daily (UTC) LLM token allowance per user."""

    def __init__(self, redis: Redis, *, daily_limit: int) -> None:
        self._redis = redis
        self.daily_limit = daily_limit

    @staticmethod
    def _key(user_id: uuid.UUID) -> str:
        return f"tok:{user_id}:{datetime.now(UTC):%Y%m%d}"

    async def used(self, user_id: uuid.UUID) -> int:
        try:
            value = await self._redis.get(self._key(user_id))
        except RedisError:
            logger.warning("token_budget_unavailable", exc_info=True)
            return 0
        return int(value or 0)

    async def check(self, user_id: uuid.UUID) -> None:
        if await self.used(user_id) >= self.daily_limit:
            raise TokenBudgetExceededError(
                f"Daily limit of {self.daily_limit} tokens reached. It resets at 00:00 UTC."
            )

    async def add(self, user_id: uuid.UUID, tokens: int) -> None:
        if tokens <= 0:
            return
        key = self._key(user_id)
        try:
            await self._redis.incrby(key, tokens)
            await self._redis.expire(key, _BUDGET_KEY_TTL)
        except RedisError:
            logger.warning("token_budget_unavailable", exc_info=True)
