"""Shared HTTP plumbing for provider adapters: error mapping and line streaming."""

from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from app.services.llm.base import (
    LLMAuthError,
    LLMBadRequestError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)

_MAX_ERROR_BODY = 300


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after", "")
    try:
        return float(value)
    except ValueError:
        return None


def raise_for_status(response: httpx.Response, provider: str) -> None:
    status = response.status_code
    if status < 400:  # noqa: PLR2004
        return
    body = response.text[:_MAX_ERROR_BODY]  # callers read the body before calling this
    message = f"{provider} returned HTTP {status}: {body}"
    if status == 429:  # noqa: PLR2004
        raise LLMRateLimitError(message, provider=provider, retry_after=_retry_after(response))
    if status in {401, 403}:
        raise LLMAuthError(
            f"{provider} rejected the credentials (HTTP {status}).", provider=provider
        )
    if status == 408 or status >= 500:  # noqa: PLR2004
        raise LLMUnavailableError(message, provider=provider, retry_after=_retry_after(response))
    raise LLMBadRequestError(message, provider=provider)


def _transport_error(exc: httpx.HTTPError, provider: str) -> LLMError:
    if isinstance(exc, httpx.TimeoutException):
        return LLMTimeoutError(f"{provider} timed out.", provider=provider)
    return LLMUnavailableError(
        f"{provider} is unreachable: {type(exc).__name__}", provider=provider
    )


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    request_timeout: float,
    provider: str,
) -> dict[str, Any]:
    try:
        response = await client.post(
            url, json=payload, headers=dict(headers), timeout=request_timeout
        )
    except httpx.HTTPError as exc:
        raise _transport_error(exc, provider) from exc
    raise_for_status(response, provider)
    try:
        data = response.json()
    except ValueError as exc:
        raise LLMResponseError(f"{provider} returned invalid JSON.", provider=provider) from exc
    if not isinstance(data, dict):
        raise LLMResponseError(f"{provider} returned an unexpected payload.", provider=provider)
    return data


async def stream_lines(
    client: httpx.AsyncClient,
    url: str,
    *,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    request_timeout: float,
    provider: str,
) -> AsyncIterator[str]:
    """Yield non-empty response lines (SSE "data: ..." or NDJSON)."""
    try:
        async with client.stream(
            "POST", url, json=payload, headers=dict(headers), timeout=request_timeout
        ) as response:
            if response.status_code >= 400:  # noqa: PLR2004
                await response.aread()
                raise_for_status(response, provider)
            async for line in response.aiter_lines():
                if line.strip():
                    yield line.strip()
    except httpx.HTTPError as exc:
        raise _transport_error(exc, provider) from exc
