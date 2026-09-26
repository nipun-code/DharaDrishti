"""Structured JSON logging. Every log line carries the current request_id (or null)."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.context import get_request_id

# Attributes present on every LogRecord; anything else was passed via `extra=` and is emitted.
_RESERVED_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
    | {"message", "asctime", "color_message"}  # color_message: uvicorn's ANSI duplicate
)

# Third-party loggers that install their own handlers; we route them through the root JSON handler.
_THIRD_PARTY_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "arq", "alembic")


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Install the JSON handler on the root logger. Idempotent."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in _THIRD_PARTY_LOGGERS:
        lib_logger = logging.getLogger(name)
        lib_logger.handlers = []
        lib_logger.propagate = True
    # Our middleware emits the access log (with request_id), so silence uvicorn's duplicate.
    logging.getLogger("uvicorn.access").disabled = True
