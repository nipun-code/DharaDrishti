"""ASGI middleware: request id propagation, access logging, and last-resort error handling.

Implemented as pure ASGI (not BaseHTTPMiddleware) so it is safe for streaming responses (SSE)
and so the request_id contextvar is visible to every log line emitted while handling the request.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_ctx
from app.core.error_handlers import error_response

logger = logging.getLogger("app.request")

# Accept client-supplied ids only if they are short and safe to echo into headers / logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        self.app = app
        self.header_name = header_name

    def _resolve_request_id(self, scope: Scope) -> str:
        incoming = Headers(scope=scope).get(self.header_name)
        if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
            return incoming
        return uuid.uuid4().hex

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._resolve_request_id(scope)
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[self.header_name] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("unhandled_exception")
            if response_started:
                raise
            response = error_response(500, "internal_error", "An unexpected error occurred.")
            await response(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request_completed",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_ctx.reset(token)
