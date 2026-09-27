"""Question answering: JSON (POST /query) and Server-Sent Events (POST /query/stream).

SSE events: "status" {stage, message} -> "token" {text}* -> "citations" {citations} ->
"done" {QueryResponse}; or "error" {code, message, request_id} if something fails mid-stream.
The streamed tokens are the raw draft: clients should replace them with `done.answer`, which is
the verified final answer (citations cleaned, possibly revised or refused by the guardrails).
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import QueryPipelineDep, QueryUserDep
from app.core.context import get_request_id
from app.core.exceptions import AppError
from app.schemas.error import ErrorResponse
from app.schemas.query import QueryRequest, QueryResponse
from app.services.query.pipeline import ResultEvent, StatusEvent, TokenEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["query"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 422, 429, 503)
}


@router.post("", response_model=QueryResponse, responses=_ERRORS, summary="Ask a question")
async def ask(body: QueryRequest, user: QueryUserDep, pipeline: QueryPipelineDep) -> QueryResponse:
    result: QueryResponse | None = None
    async for event in pipeline.run(
        body.query, user_id=user.id, acts=body.acts, mode=body.mode, top_k=body.top_k
    ):
        if isinstance(event, ResultEvent):
            result = event.response
    if result is None:  # pragma: no cover - the pipeline always ends with a result
        raise AppError("The pipeline produced no answer.")
    return result


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/stream",
    responses={200: {"content": {"text/event-stream": {}}}, **_ERRORS},
    summary="Ask a question, streaming the answer as Server-Sent Events",
)
async def ask_stream(
    body: QueryRequest, user: QueryUserDep, pipeline: QueryPipelineDep
) -> StreamingResponse:
    # Validate before the stream starts, so bad input is a normal HTTP 422.
    pipeline.validate(body.query)
    request_id = get_request_id()

    async def events() -> AsyncIterator[str]:
        try:
            async for event in pipeline.run(
                body.query, user_id=user.id, acts=body.acts, mode=body.mode, top_k=body.top_k
            ):
                if isinstance(event, StatusEvent):
                    yield _sse("status", {"stage": event.stage, "message": event.message})
                elif isinstance(event, TokenEvent):
                    yield _sse("token", {"text": event.text})
                else:
                    payload = event.response.model_dump(mode="json")
                    yield _sse("citations", {"citations": payload["citations"]})
                    yield _sse("done", payload)
        except AppError as exc:
            yield _sse(
                "error", {"code": exc.code, "message": exc.message, "request_id": request_id}
            )
        except Exception:
            logger.exception("stream_failed")
            yield _sse(
                "error",
                {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "request_id": request_id,
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
