from unittest.mock import patch

from app.workers import worker
from app.workers.worker import WorkerSettings, on_shutdown, on_startup, ping


async def test_ping_task_returns_pong() -> None:
    assert await ping({}) == "pong"


async def test_worker_lifecycle_hooks_run() -> None:
    await on_startup({})
    await on_shutdown({})


def test_worker_settings_registers_tasks() -> None:
    assert [f.name for f in WorkerSettings.functions] == ["ping"]  # type: ignore[union-attr]
    assert WorkerSettings.redis_settings.host


def test_main_configures_logging_then_runs_worker() -> None:
    with (
        patch.object(worker, "configure_logging") as configure,
        patch.object(worker, "run_worker") as run,
    ):
        worker.main()

    configure.assert_called_once()
    run.assert_called_once_with(WorkerSettings)
