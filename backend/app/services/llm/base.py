"""Provider-agnostic LLM interface, value types and error taxonomy."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: tuple[ChatMessage, ...]
    max_tokens: int
    temperature: float = 0.0
    json_mode: bool = False
    purpose: str = "answer"  # e.g. rewrite / topic / answer / faithfulness (logging, tests)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# A stream yields text deltas (str) and ends with exactly one LLMResponse (full text + usage).
StreamItem = str | LLMResponse


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[StreamItem]: ...


# ---------------------------------------------------------------- errors
class LLMError(Exception):
    """Base class. `retryable` errors are retried with backoff on the same provider; any error
    moves on to the next provider in the fallback chain once retries are exhausted."""

    retryable = False

    def __init__(
        self, message: str, *, provider: str = "", retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retry_after = retry_after


class LLMTimeoutError(LLMError):
    retryable = True


class LLMRateLimitError(LLMError):
    retryable = True


class LLMUnavailableError(LLMError):
    """Network failure or 5xx."""

    retryable = True


class LLMAuthError(LLMError):
    """401/403: bad or missing API key."""


class LLMBadRequestError(LLMError):
    """4xx other than auth/rate-limit: the request itself is wrong."""


class LLMResponseError(LLMError):
    """The provider answered 200 but the payload was unusable."""


class LLMStreamInterruptedError(LLMError):
    """A stream failed after tokens were already emitted; cannot fall back transparently."""


class AllProvidersFailedError(LLMError):
    """Every configured provider failed (or none is configured)."""


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) when a provider doesn't report usage."""
    return max(1, len(text) // 4)
