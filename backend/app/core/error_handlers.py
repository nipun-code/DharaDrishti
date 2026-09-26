"""Global exception handlers that render the error envelope:
{"error": {"code": "...", "message": "...", "request_id": "..."}}
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id
from app.core.exceptions import AppError
from app.schemas.error import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)

_HTTP_STATUS_CODES: Mapping[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
    503: "service_unavailable",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build a JSONResponse carrying the standard error envelope."""
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=get_request_id(), details=details)
    )
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body, exclude_none=True),
        headers=dict(headers) if headers else None,
    )


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101  # registered for AppError only
    log = logger.error if exc.status_code >= 500 else logger.info  # noqa: PLR2004
    log("app_error", extra={"error_code": exc.code, "status_code": exc.status_code})
    return error_response(
        exc.status_code, exc.code, exc.message, details=exc.details, headers=exc.headers
    )


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def validation_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    # Drop the raw input and pydantic docs URL so we never echo request payloads back verbatim.
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return error_response(422, "validation_error", "Request validation failed.", details=errors)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all global handlers. Unhandled exceptions are caught by RequestContextMiddleware."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
