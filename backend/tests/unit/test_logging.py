import json
import logging
import sys

import httpx

from app.core.context import request_id_ctx
from app.core.logging import JsonFormatter, configure_logging


def make_record(msg: str = "hello", **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, msg, (), None)
    record.__dict__.update(extra)
    return record


def test_formatter_emits_json_with_request_id() -> None:
    token = request_id_ctx.set("req-42")
    try:
        line = JsonFormatter().format(make_record(dependency="redis"))
    finally:
        request_id_ctx.reset(token)

    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["request_id"] == "req-42"
    assert payload["dependency"] == "redis"
    assert "timestamp" in payload


def test_formatter_request_id_null_outside_request() -> None:
    payload = json.loads(JsonFormatter().format(make_record()))

    assert payload["request_id"] is None


def _raise_value_error() -> None:
    raise ValueError("bad")


def test_formatter_includes_exception() -> None:
    try:
        _raise_value_error()
    except ValueError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
        )

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: bad" in payload["exc_info"]


def test_configure_logging_installs_json_handler() -> None:
    configure_logging("DEBUG")

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert logging.getLogger("uvicorn.access").disabled
    assert logging.getLogger("uvicorn.error").propagate


class ListHandler(logging.Handler):
    """Formats at emit time (like the real stdout handler), while the request context is live."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))


async def test_access_log_line_has_request_id(client: httpx.AsyncClient) -> None:
    handler = ListHandler()
    request_logger = logging.getLogger("app.request")
    request_logger.addHandler(handler)
    request_logger.setLevel(logging.INFO)
    try:
        response = await client.get("/health/live")
    finally:
        request_logger.removeHandler(handler)

    [line] = [ln for ln in handler.lines if ln["message"] == "request_completed"]
    assert line["request_id"] == response.headers["X-Request-ID"]
    assert line["method"] == "GET"
    assert line["path"] == "/health/live"
    assert line["status_code"] == 200
    assert isinstance(line["duration_ms"], float)
