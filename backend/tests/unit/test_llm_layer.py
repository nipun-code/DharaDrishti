"""LLM providers (via httpx.MockTransport — never a real API), retries, fallback and factory."""

import json
import random
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.llm.base import (
    AllProvidersFailedError,
    ChatMessage,
    LLMAuthError,
    LLMBadRequestError,
    LLMError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMStreamInterruptedError,
    LLMTimeoutError,
    LLMUnavailableError,
    StreamItem,
)
from app.services.llm.factory import build_llm, build_providers
from app.services.llm.fallback import FallbackLLM
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider
from app.services.llm.ollama import OllamaProvider
from app.services.llm.retry import RetryPolicy, call_with_retries

REQUEST = LLMRequest(
    messages=(ChatMessage("system", "be brief"), ChatMessage("user", "hello")),
    max_tokens=50,
    temperature=0.1,
)
JSON_REQUEST = LLMRequest(messages=REQUEST.messages, max_tokens=20, json_mode=True, purpose="topic")

Handler = Callable[[httpx.Request], httpx.Response]


def client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def sse(*chunks: Any, done: bool = False) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


async def collect(stream: AsyncIterator[StreamItem]) -> tuple[list[str], LLMResponse]:
    deltas: list[str] = []
    final: LLMResponse | None = None
    async for item in stream:
        if isinstance(item, str):
            deltas.append(item)
        else:
            final = item
    assert final is not None
    return deltas, final


# ---------------------------------------------------------------- Groq
def groq(handler: Handler) -> GroqProvider:
    return GroqProvider(
        client(handler),
        api_key="gsk-test",
        model="groq-model",
        base_url="https://groq.test/v1",
        timeout=5,
    )


async def test_groq_complete_request_and_response() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    response = await groq(handler).complete(JSON_REQUEST)

    assert seen["url"] == "https://groq.test/v1/chat/completions"
    assert seen["auth"] == "Bearer gsk-test"
    assert seen["body"]["model"] == "groq-model"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"][0] == {"role": "system", "content": "be brief"}
    assert (response.text, response.prompt_tokens, response.completion_tokens) == (
        '{"ok": true}',
        12,
        3,
    )
    assert (response.provider, response.model) == ("groq", "groq-model")


async def test_groq_stream_with_usage() -> None:
    body = sse(
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
        done=True,
    )

    deltas, final = await collect(groq(lambda r: httpx.Response(200, content=body)).stream(REQUEST))

    assert deltas == ["Hel", "lo"]
    assert (final.text, final.prompt_tokens, final.completion_tokens) == ("Hello", 7, 2)


async def test_groq_bad_payload() -> None:
    with pytest.raises(LLMResponseError):
        await groq(lambda r: httpx.Response(200, json={"choices": []})).complete(REQUEST)


# ---------------------------------------------------------------- Gemini
def gemini(handler: Handler) -> GeminiProvider:
    return GeminiProvider(
        client(handler),
        api_key="gem-key",
        model="gem-model",
        base_url="https://gem.test/v1beta",
        timeout=5,
    )


async def test_gemini_complete_maps_roles_and_keeps_key_out_of_url() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "Hi "}, {"text": "there"}]}}],
                "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 2},
            },
        )

    response = await gemini(handler).complete(JSON_REQUEST)

    assert seen["url"] == "https://gem.test/v1beta/models/gem-model:generateContent"
    assert "gem-key" not in seen["url"]
    assert seen["key"] == "gem-key"
    assert seen["body"]["systemInstruction"] == {"parts": [{"text": "be brief"}]}
    assert seen["body"]["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert (response.text, response.prompt_tokens, response.completion_tokens) == ("Hi there", 9, 2)


async def test_gemini_stream() -> None:
    body = sse(
        {"candidates": [{"content": {"parts": [{"text": "A"}]}}]},
        {
            "candidates": [{"content": {"parts": [{"text": "B"}]}}],
            "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2},
        },
    )

    deltas, final = await collect(
        gemini(lambda r: httpx.Response(200, content=body)).stream(REQUEST)
    )

    assert deltas == ["A", "B"]
    assert (final.text, final.prompt_tokens) == ("AB", 4)


@pytest.mark.parametrize(
    "payload", [{"promptFeedback": {"blockReason": "SAFETY"}}, {"candidates": []}]
)
async def test_gemini_blocked_or_empty(payload: dict[str, Any]) -> None:
    with pytest.raises(LLMResponseError):
        await gemini(lambda r: httpx.Response(200, json=payload)).complete(REQUEST)


# ---------------------------------------------------------------- Ollama
def ollama(handler: Handler) -> OllamaProvider:
    return OllamaProvider(
        client(handler), model="llama-test", base_url="http://ollama.test:11434", timeout=5
    )


async def test_ollama_complete_and_json_format() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"message": {"content": "{}"}, "prompt_eval_count": 5, "eval_count": 1}
        )

    response = await ollama(handler).complete(JSON_REQUEST)

    assert seen["url"] == "http://ollama.test:11434/api/chat"
    assert seen["body"]["format"] == "json"
    assert seen["body"]["options"] == {"temperature": 0.0, "num_predict": 20}
    assert (response.text, response.prompt_tokens, response.completion_tokens) == ("{}", 5, 1)


async def test_ollama_stream_ndjson() -> None:
    lines = [
        {"message": {"content": "x"}, "done": False},
        {"message": {"content": "y"}, "done": True, "prompt_eval_count": 3, "eval_count": 2},
    ]
    body = "\n".join(json.dumps(line) for line in lines).encode()

    deltas, final = await collect(
        ollama(lambda r: httpx.Response(200, content=body)).stream(REQUEST)
    )

    assert deltas == ["x", "y"]
    assert (final.text, final.completion_tokens) == ("xy", 2)


async def test_ollama_stream_error_line() -> None:
    body = json.dumps({"error": "model not found"}).encode()

    with pytest.raises(LLMResponseError, match="model not found"):
        await collect(ollama(lambda r: httpx.Response(200, content=body)).stream(REQUEST))


# ---------------------------------------------------------------- error mapping
@pytest.mark.parametrize(
    ("status", "headers", "error", "retryable"),
    [
        (429, {"retry-after": "3"}, LLMRateLimitError, True),
        (401, {}, LLMAuthError, False),
        (403, {}, LLMAuthError, False),
        (500, {}, LLMUnavailableError, True),
        (503, {}, LLMUnavailableError, True),
        (400, {}, LLMBadRequestError, False),
    ],
)
async def test_http_errors_mapped(
    status: int, headers: dict[str, str], error: type[LLMError], retryable: bool
) -> None:
    provider = groq(lambda r: httpx.Response(status, headers=headers, text="provider says no"))

    with pytest.raises(error) as info:
        await provider.complete(REQUEST)

    assert info.value.retryable is retryable
    assert "gsk-test" not in str(info.value)
    if status == 429:
        assert info.value.retry_after == 3.0


async def test_http_errors_mapped_for_streams_too() -> None:
    with pytest.raises(LLMRateLimitError):
        await collect(groq(lambda r: httpx.Response(429, text="slow down")).stream(REQUEST))


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (httpx.ReadTimeout("slow"), LLMTimeoutError),
        (httpx.ConnectError("refused"), LLMUnavailableError),
    ],
)
async def test_transport_errors_mapped(exc: Exception, error: type[LLMError]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    with pytest.raises(error):
        await ollama(handler).complete(REQUEST)


async def test_invalid_json_body() -> None:
    with pytest.raises(LLMResponseError, match="invalid JSON"):
        await groq(lambda r: httpx.Response(200, text="<html>")).complete(REQUEST)


# ---------------------------------------------------------------- retry policy
def test_backoff_is_capped_exponential_with_full_jitter() -> None:
    policy = RetryPolicy(attempts=5, base_delay=0.5, max_delay=4.0)
    rand = random.Random(0)

    for retry, cap in enumerate([0.5, 1.0, 2.0, 4.0, 4.0]):
        delays = [policy.delay(retry, None, rand) for _ in range(200)]
        assert all(0 <= d <= cap for d in delays)
        assert max(delays) > cap * 0.8  # jitter spreads across the whole range


def test_retry_after_is_honoured_but_capped() -> None:
    policy = RetryPolicy(max_delay=5.0)

    assert policy.delay(0, 2.5, random.Random()) == 2.5
    assert policy.delay(0, 60, random.Random()) == 5.0


class Flaky:
    def __init__(self, *outcomes: Exception | str) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_retries_retryable_errors_then_succeeds() -> None:
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    op = Flaky(LLMTimeoutError("t"), LLMRateLimitError("r", retry_after=1.0), "ok")

    result = await call_with_retries(
        op, RetryPolicy(attempts=3), sleep=sleep, rand=random.Random(1)
    )

    assert result == "ok"
    assert op.calls == 3
    assert len(sleeps) == 2
    assert sleeps[1] == 1.0


async def test_non_retryable_error_is_not_retried() -> None:
    op = Flaky(LLMAuthError("bad key"), "never")

    with pytest.raises(LLMAuthError):
        await call_with_retries(op, RetryPolicy(attempts=3), sleep=_no_sleep)

    assert op.calls == 1


async def test_gives_up_after_max_attempts() -> None:
    op = Flaky(*[LLMUnavailableError("down")] * 5)

    with pytest.raises(LLMUnavailableError):
        await call_with_retries(op, RetryPolicy(attempts=3), sleep=_no_sleep)

    assert op.calls == 3


async def _no_sleep(_: float) -> None:
    return None


# ---------------------------------------------------------------- fallback chain
class ScriptedProvider:
    def __init__(self, name: str, *outcomes: Exception | str) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.outcomes = list(outcomes)
        self.calls = 0

    def _next(self) -> str:
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(self._next(), self.name, self.model, 1, 1)

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamItem]:
        text = self._next()
        for part in text.split("|"):
            if part == "BOOM":
                raise LLMUnavailableError("mid-stream failure")
            yield part
        yield LLMResponse(text.replace("|", ""), self.name, self.model, 1, 1)


def chain(*providers: ScriptedProvider, attempts: int = 2) -> FallbackLLM:
    return FallbackLLM(list(providers), RetryPolicy(attempts=attempts), sleep=_no_sleep)


async def test_first_healthy_provider_answers() -> None:
    groq_p, gemini_p = (
        ScriptedProvider("groq", "from groq"),
        ScriptedProvider("gemini", "from gemini"),
    )

    response = await chain(groq_p, gemini_p).complete(REQUEST)

    assert (response.text, response.provider) == ("from groq", "groq")
    assert gemini_p.calls == 0


async def test_falls_back_after_retries_exhausted() -> None:
    groq_p = ScriptedProvider("groq", LLMUnavailableError("down"))
    gemini_p = ScriptedProvider("gemini", "from gemini")

    response = await chain(groq_p, gemini_p, attempts=3).complete(REQUEST)

    assert response.provider == "gemini"
    assert groq_p.calls == 3  # retried on the same provider first


async def test_non_retryable_error_falls_back_immediately() -> None:
    groq_p = ScriptedProvider("groq", LLMAuthError("bad key"))
    ollama_p = ScriptedProvider("ollama", "local")

    response = await chain(groq_p, ollama_p, attempts=3).complete(REQUEST)

    assert response.provider == "ollama"
    assert groq_p.calls == 1


async def test_all_providers_failing_raises() -> None:
    with pytest.raises(
        AllProvidersFailedError, match="groq: LLMAuthError; gemini: LLMTimeoutError"
    ):
        await chain(
            ScriptedProvider("groq", LLMAuthError("x")),
            ScriptedProvider("gemini", LLMTimeoutError("y")),
        ).complete(REQUEST)


async def test_no_providers_configured() -> None:
    with pytest.raises(AllProvidersFailedError, match="No LLM provider"):
        await chain().complete(REQUEST)
    with pytest.raises(AllProvidersFailedError, match="No LLM provider"):
        await collect(chain().stream(REQUEST))


async def test_stream_retries_and_falls_back_before_first_token() -> None:
    groq_p = ScriptedProvider("groq", LLMRateLimitError("slow"))
    gemini_p = ScriptedProvider("gemini", "a|b")

    deltas, final = await collect(chain(groq_p, gemini_p).stream(REQUEST))

    assert deltas == ["a", "b"]
    assert final.provider == "gemini"
    assert groq_p.calls == 2


async def test_stream_failure_after_tokens_is_not_retried() -> None:
    groq_p = ScriptedProvider("groq", "partial|BOOM")
    gemini_p = ScriptedProvider("gemini", "never used")

    with pytest.raises(LLMStreamInterruptedError):
        await collect(chain(groq_p, gemini_p).stream(REQUEST))
    assert gemini_p.calls == 0


async def test_stream_all_failing() -> None:
    with pytest.raises(AllProvidersFailedError):
        await collect(chain(ScriptedProvider("groq", LLMAuthError("x"))).stream(REQUEST))


# ---------------------------------------------------------------- factory
def test_factory_builds_configured_providers_in_order(settings: Settings) -> None:
    configured = settings.model_copy(
        update={
            "llm_providers": "ollama, groq, gemini, mystery",
            "groq_api_key": SecretStr("k"),
            "groq_model": "g-model",
            "gemini_api_key": None,  # not configured -> skipped
            "gemini_model": "gem",
            "ollama_model": "o-model",
        }
    )

    providers = build_providers(configured, httpx.AsyncClient())

    assert [(p.name, p.model) for p in providers] == [("ollama", "o-model"), ("groq", "g-model")]


def test_factory_with_nothing_configured(settings: Settings) -> None:
    llm = build_llm(settings, httpx.AsyncClient())

    assert llm.providers == []
