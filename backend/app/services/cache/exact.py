"""Exact-match answer cache in Redis (SPEC §7.2).

Key = normalized (PII-redacted) query + act filter + retrieval mode + top_k + prompt version.
Only non-refused answers are stored. Cache errors never fail a request.
"""

import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.services.generation.prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)


def cache_key(query: str, acts: Sequence[str] | None, mode: str, top_k: int) -> str:
    normalized = " ".join(query.lower().split())
    parts = [normalized, ",".join(sorted(a.upper() for a in acts or [])), mode, str(top_k)]
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
    return f"qa:{PROMPT_VERSION}:{digest}"


class AnswerCache:
    def __init__(self, redis: Redis, *, ttl_seconds: int, enabled: bool = True) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self.enabled = enabled

    async def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            raw = await self._redis.get(key)
        except RedisError:
            logger.warning("cache_get_failed", exc_info=True)
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    async def set(self, key: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            await self._redis.set(key, json.dumps(payload, default=str), ex=self._ttl)
        except RedisError:
            logger.warning("cache_set_failed", exc_info=True)
