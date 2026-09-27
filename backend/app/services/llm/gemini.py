"""Google Gemini (free tier) via the Generative Language REST API."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.services.llm.base import (
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    StreamItem,
    estimate_tokens,
)
from app.services.llm.http import post_json, stream_lines


class GeminiProvider:
    name = "gemini"

    def __init__(
        self, client: httpx.AsyncClient, *, api_key: str, model: str, base_url: str, timeout: float
    ) -> None:
        self._client = client
        self._api_key = api_key
        self.model = model
        self._base = f"{base_url.rstrip('/')}/models/{model}"
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        # Header, not ?key=..., so the key never appears in URLs or access logs.
        return {"x-goog-api-key": self._api_key}

    def _payload(self, request: LLMRequest) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages
            if m.role != "system"
        ]
        config: dict[str, Any] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens,
        }
        if request.json_mode:
            config["responseMimeType"] = "application/json"
        payload: dict[str, Any] = {"contents": contents, "generationConfig": config}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return payload

    def _text(self, data: dict[str, Any]) -> str:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise LLMResponseError(f"gemini blocked the prompt ({block}).", provider=self.name)
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        data = await post_json(
            self._client,
            f"{self._base}:generateContent",
            payload=self._payload(request),
            headers=self._headers(),
            request_timeout=self._timeout,
            provider=self.name,
        )
        text = self._text(data)
        if not data.get("candidates"):
            raise LLMResponseError("gemini returned no candidates.", provider=self.name)
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=int(usage.get("promptTokenCount") or 0),
            completion_tokens=int(usage.get("candidatesTokenCount") or estimate_tokens(text)),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamItem]:
        parts: list[str] = []
        usage: dict[str, Any] = {}
        async for line in stream_lines(
            self._client,
            f"{self._base}:streamGenerateContent?alt=sse",
            payload=self._payload(request),
            headers=self._headers(),
            request_timeout=self._timeout,
            provider=self.name,
        ):
            if not line.startswith("data:"):
                continue
            try:
                chunk = json.loads(line[5:].strip())
            except ValueError as exc:
                raise LLMResponseError(
                    "gemini sent an invalid stream chunk.", provider=self.name
                ) from exc
            usage = chunk.get("usageMetadata") or usage
            delta = self._text(chunk)
            if delta:
                parts.append(delta)
                yield delta
        text = "".join(parts)
        yield LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=int(usage.get("promptTokenCount") or 0),
            completion_tokens=int(usage.get("candidatesTokenCount") or estimate_tokens(text)),
        )
