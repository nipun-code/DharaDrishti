"""Domain exceptions. Services raise these; global handlers render the error envelope."""

from collections.abc import Mapping
from typing import Any, ClassVar


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code: ClassVar[int] = 500
    code: ClassVar[str] = "internal_error"
    default_message: ClassVar[str] = "An unexpected error occurred."
    default_headers: ClassVar[Mapping[str, str] | None] = None

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details
        self.headers: dict[str, str] | None = (
            dict(headers) if headers is not None else dict(self.default_headers or {}) or None
        )
        super().__init__(self.message)


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    default_message = "The request is invalid."


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    default_message = "Authentication is required."
    default_headers = {"WWW-Authenticate": "Bearer"}  # noqa: RUF012  # read-only class constant


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    default_message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    default_message = "The request conflicts with the current state of the resource."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    default_message = "The request body is too large."


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    code = "unsupported_media_type"
    default_message = "Unsupported file type."


class InvalidQueryError(AppError):
    status_code = 422
    code = "invalid_query"
    default_message = "The question is not valid."


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    default_message = "Too many requests. Please wait a moment and try again."


class TokenBudgetExceededError(AppError):
    status_code = 429
    code = "token_budget_exceeded"
    default_message = "You have used today's question allowance. It resets at 00:00 UTC."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    default_message = "A required service is temporarily unavailable."
