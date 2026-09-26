"""Per-request context propagated through contextvars (safe across async tasks)."""

from contextvars import ContextVar

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the request id of the request currently being handled, if any."""
    return request_id_ctx.get()
