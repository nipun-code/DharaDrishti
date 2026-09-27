"""Ollama (local models) via its /api/chat endpoint."""

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


class OllamaProvider:
    name = "ollama"

    def __init__(
        self, client: httpx.AsyncClient, *, model: str, base_url: str, timeout: float
    ) -> None:
        self._client = client
        self.model = model
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self._timeout = timeout

    def _payload(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": stream,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        if request.json_mode:
            payload["format"] = "json"
        return payload

    def _response(self, text: str, data: dict[str, Any]) -> LLMResponse:
        return LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or estimate_tokens(text)),
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        data = await post_json(
            self._client,
            self._url,
            payload=self._payload(request, stream=False),
            headers={},
            request_timeout=self._timeout,
            provider=self.name,
        )
        message = data.get("message")
        if not isinstance(message, dict):
            raise LLMResponseError("ollama returned no message.", provider=self.name)
        return self._response(str(message.get("content") or ""), data)

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamItem]:
        parts: list[str] = []
        final: dict[str, Any] = {}
        async for line in stream_lines(
            self._client,
            self._url,
            payload=self._payload(request, stream=True),
            headers={},
            request_timeout=self._timeout,
            provider=self.name,
        ):
            try:
                chunk = json.loads(line)
            except ValueError as exc:
                raise LLMResponseError(
                    "ollama sent an invalid stream chunk.", provider=self.name
                ) from exc
            if chunk.get("error"):
                raise LLMResponseError(f"ollama error: {chunk['error']}", provider=self.name)
            delta = (chunk.get("message") or {}).get("content")
            if delta:
                parts.append(delta)
                yield delta
            if chunk.get("done"):
                final = chunk
                break
        yield self._response("".join(parts), final)
