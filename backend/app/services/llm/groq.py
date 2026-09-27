"""Groq (free tier) via its OpenAI-compatible Chat Completions API."""

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


class GroqProvider:
    name = "groq"

    def __init__(
        self, client: httpx.AsyncClient, *, api_key: str, model: str, base_url: str, timeout: float
    ) -> None:
        self._client = client
        self._api_key = api_key
        self.model = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _payload(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        data = await post_json(
            self._client,
            self._url,
            payload=self._payload(request, stream=False),
            headers=self._headers(),
            request_timeout=self._timeout,
            provider=self.name,
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("groq returned no choices.", provider=self.name) from exc
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or estimate_tokens(text)),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamItem]:
        parts: list[str] = []
        usage: dict[str, Any] = {}
        async for line in stream_lines(
            self._client,
            self._url,
            payload=self._payload(request, stream=True),
            headers=self._headers(),
            request_timeout=self._timeout,
            provider=self.name,
        ):
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError as exc:
                raise LLMResponseError(
                    "groq sent an invalid stream chunk.", provider=self.name
                ) from exc
            usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage") or usage
            for choice in chunk.get("choices") or []:
                delta = (choice.get("delta") or {}).get("content")
                if delta:
                    parts.append(delta)
                    yield delta
        text = "".join(parts)
        yield LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or estimate_tokens(text)),
        )
