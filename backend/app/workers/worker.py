"""ARQ background worker. Run with: python -m app.workers.worker

(Used instead of the `arq` CLI, which installs its own plain-text logging config.)

Real tasks (ingestion, evaluation) are registered in later phases.
"""

import logging
from collections.abc import Sequence
from typing import Any

from arq import run_worker
from arq.connections import RedisSettings
from arq.typing import StartupShutdown, WorkerCoroutine, WorkerSettingsBase
from arq.worker import Function, func

from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


async def ping(ctx: dict[Any, Any]) -> str:
    """Trivial task used to verify the worker is consuming jobs."""
    return "pong"


async def on_startup(ctx: dict[Any, Any]) -> None:
    logger.info("worker_startup")


async def on_shutdown(ctx: dict[Any, Any]) -> None:
    logger.info("worker_shutdown")


class WorkerSettings(WorkerSettingsBase):
    functions: Sequence[WorkerCoroutine | Function] = (func(ping, name="ping"),)
    on_startup: StartupShutdown | None = on_startup
    on_shutdown: StartupShutdown | None = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)


def main() -> None:
    configure_logging(get_settings().log_level)
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
