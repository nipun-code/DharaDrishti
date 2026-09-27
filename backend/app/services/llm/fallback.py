"""Provider fallback chain (e.g. groq -> gemini -> ollama), each provider with retries."""

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from app.services.llm.base import (
    AllProvidersFailedError,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMStreamInterruptedError,
    StreamItem,
)
from app.services.llm.retry import RetryPolicy, Sleep, call_with_retries

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """What the rest of the app uses: FallbackLLM in production, a fake in tests."""

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[StreamItem]: ...


class FallbackLLM:
    def __init__(
        self,
        providers: Sequence[LLMProvider],
        policy: RetryPolicy,
        *,
        sleep: Sleep = asyncio.sleep,
        rand: random.Random | None = None,
    ) -> None:
        self.providers = list(providers)
        self._policy = policy
        self._sleep = sleep
        self._rand = rand or random.Random()  # noqa: S311  # jitter only

    def _no_providers(self) -> AllProvidersFailedError:
        return AllProvidersFailedError(
            "No LLM provider is configured. Set GROQ_*, GEMINI_* or OLLAMA_* in .env."
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.providers:
            raise self._no_providers()
        failures: list[str] = []
        for provider in self.providers:
            try:
                return await call_with_retries(
                    lambda p=provider: p.complete(request),  # type: ignore[misc]
                    self._policy,
                    sleep=self._sleep,
                    rand=self._rand,
                    label=provider.name,
                )
            except LLMError as exc:
                failures.append(f"{provider.name}: {type(exc).__name__}")
                logger.warning(
                    "llm_provider_failed",
                    extra={
                        "provider": provider.name,
                        "purpose": request.purpose,
                        "error": str(exc),
                    },
                )
        raise AllProvidersFailedError("All LLM providers failed (" + "; ".join(failures) + ").")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamItem]:
        """Stream from the first provider that works. Retrying/falling back is only possible
        before the first token; a failure after that raises LLMStreamInterruptedError."""
        if not self.providers:
            raise self._no_providers()
        failures: list[str] = []
        for provider in self.providers:
            for attempt in range(self._policy.attempts):
                emitted = False
                try:
                    async for item in provider.stream(request):
                        if isinstance(item, str):
                            emitted = True
                        yield item
                except LLMError as exc:
                    if emitted:
                        raise LLMStreamInterruptedError(
                            f"{provider.name} stream failed mid-answer.", provider=provider.name
                        ) from exc
                    last = attempt == self._policy.attempts - 1
                    logger.warning(
                        "llm_stream_attempt_failed",
                        extra={
                            "provider": provider.name,
                            "attempt": attempt + 1,
                            "error": str(exc),
                        },
                    )
                    if not exc.retryable or last:
                        failures.append(f"{provider.name}: {type(exc).__name__}")
                        break
                    await self._sleep(self._policy.delay(attempt, exc.retry_after, self._rand))
                else:
                    return
        raise AllProvidersFailedError("All LLM providers failed (" + "; ".join(failures) + ").")
