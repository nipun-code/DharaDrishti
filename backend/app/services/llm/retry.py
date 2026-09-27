"""Exponential backoff with full jitter (AWS Architecture Blog, "Exponential Backoff And Jitter").

    delay_n = uniform(0, min(max_delay, base * 2**n)),  n = 0, 1, 2, ...

A server-provided Retry-After takes precedence (capped at max_delay).
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from app.services.llm.base import LLMError

logger = logging.getLogger(__name__)
T = TypeVar("T")

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0

    def delay(self, retry_number: int, retry_after: float | None, rand: random.Random) -> float:
        if retry_after is not None:
            return min(self.max_delay, max(0.0, retry_after))
        cap = min(self.max_delay, self.base_delay * (2**retry_number))
        return rand.uniform(0, cap)


async def call_with_retries(
    operation: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    sleep: Sleep = asyncio.sleep,
    rand: random.Random | None = None,
    label: str = "",
) -> T:
    """Run `operation`, retrying retryable LLMErrors up to `policy.attempts` times in total."""
    rand = rand or random.Random()  # noqa: S311  # jitter, not cryptography
    for attempt in range(policy.attempts):
        try:
            return await operation()
        except LLMError as exc:
            if not exc.retryable or attempt == policy.attempts - 1:
                raise
            delay = policy.delay(attempt, exc.retry_after, rand)
            logger.warning(
                "llm_retry",
                extra={
                    "provider": label,
                    "attempt": attempt + 1,
                    "error": type(exc).__name__,
                    "delay_s": round(delay, 3),
                },
            )
            await sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
