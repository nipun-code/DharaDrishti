import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

from app.core.context import get_request_id
from app.services.ingestion.pipeline import IngestionPipeline
from app.workers import worker
from app.workers.queue import INGEST_DOCUMENT_JOB, ArqJobQueue
from app.workers.worker import WorkerSettings, ingest_document, on_shutdown, on_startup, ping


async def test_ping_task_returns_pong() -> None:
    assert await ping({}) == "pong"


async def test_startup_builds_pipeline_and_shutdown_disposes_engine() -> None:
    ctx: dict[Any, Any] = {}

    await on_startup(ctx)

    assert isinstance(ctx["pipeline"], IngestionPipeline)
    await on_shutdown(ctx)


async def test_shutdown_without_startup_is_safe() -> None:
    await on_shutdown({})


async def test_ingest_document_job_runs_pipeline_with_job_request_id() -> None:
    seen: list[str | None] = []
    pipeline = AsyncMock()
    pipeline.run.side_effect = lambda _id: seen.append(get_request_id())
    document_id = uuid.uuid4()

    await ingest_document({"pipeline": pipeline, "job_id": "abc"}, str(document_id))

    pipeline.run.assert_awaited_once_with(document_id)
    assert seen == ["job:abc"]
    assert get_request_id() is None


def test_worker_settings_registers_tasks() -> None:
    names = [f.name for f in WorkerSettings.functions]  # type: ignore[union-attr]
    assert names == ["ping", INGEST_DOCUMENT_JOB]
    assert WorkerSettings.redis_settings.host


async def test_arq_queue_uses_deterministic_job_id() -> None:
    redis = AsyncMock()
    document_id = uuid.uuid4()

    await ArqJobQueue(redis).enqueue_ingestion(document_id)

    redis.enqueue_job.assert_awaited_once_with(
        INGEST_DOCUMENT_JOB, str(document_id), _job_id=f"ingest:{document_id}"
    )


def test_main_configures_logging_then_runs_worker() -> None:
    with (
        patch.object(worker, "configure_logging") as configure,
        patch.object(worker, "run_worker") as run,
    ):
        worker.main()

    configure.assert_called_once()
    run.assert_called_once_with(WorkerSettings)
