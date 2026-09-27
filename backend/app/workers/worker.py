"""ARQ background worker. Run with: python -m app.workers.worker

(Used instead of the `arq` CLI, which installs its own plain-text logging config.)
"""

import logging
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
from arq import run_worker
from arq.connections import RedisSettings
from arq.typing import StartupShutdown, WorkerCoroutine, WorkerSettingsBase
from arq.worker import Function, func

from app.core.config import get_settings
from app.core.context import request_id_ctx
from app.core.logging import configure_logging
from app.db.redis import create_redis
from app.db.session import create_engine, create_session_factory
from app.services.evaluation.service import EvaluationService, build_runner
from app.services.ingestion.embedder import SentenceTransformerEmbedder
from app.services.ingestion.pipeline import IngestionPipeline
from app.services.ingestion.storage import DocumentStorage
from app.services.llm.factory import build_llm
from app.services.retrieval.reranker import CrossEncoderReranker
from app.workers.queue import INGEST_DOCUMENT_JOB, RUN_EVALUATION_JOB

logger = logging.getLogger(__name__)


async def ping(ctx: dict[Any, Any]) -> str:
    """Trivial task used to verify the worker is consuming jobs."""
    return "pong"


async def ingest_document(ctx: dict[Any, Any], document_id: str) -> None:
    # Tag every log line of this job with the job id, like request ids in the API.
    token = request_id_ctx.set(f"job:{ctx.get('job_id', 'unknown')}")
    try:
        pipeline: IngestionPipeline = ctx["pipeline"]
        await pipeline.run(uuid.UUID(document_id))
    finally:
        request_id_ctx.reset(token)


async def run_evaluation(ctx: dict[Any, Any], eval_run_id: str) -> None:
    token = request_id_ctx.set(f"job:{ctx.get('job_id', 'unknown')}")
    try:
        settings = get_settings()
        factory = ctx["session_factory"]
        runner = build_runner(
            settings,
            factory,
            embedder=ctx["embedder"],
            reranker=ctx["reranker"],
            llm=ctx["llm"],
            redis=ctx["app_redis"],
        )
        await EvaluationService(factory, settings).execute(uuid.UUID(eval_run_id), runner)
    finally:
        request_id_ctx.reset(token)


async def on_startup(ctx: dict[Any, Any]) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    ctx["engine"] = engine
    ctx["session_factory"] = factory
    # One copy of each model per worker process; they load lazily on first use.
    ctx["embedder"] = SentenceTransformerEmbedder(
        settings.embedding_model_name,
        batch_size=settings.embedding_batch_size,
        device=settings.embedding_device,
        query_instruction=settings.embedding_query_instruction,
    )
    ctx["reranker"] = CrossEncoderReranker(
        settings.reranker_model_name,
        device=settings.embedding_device,
        max_length=settings.reranker_max_length,
        batch_size=settings.reranker_batch_size,
    )
    ctx["http"] = httpx.AsyncClient()
    ctx["llm"] = build_llm(settings, ctx["http"])
    ctx["app_redis"] = create_redis(settings)
    ctx["pipeline"] = IngestionPipeline(
        session_factory=factory,
        embedder=ctx["embedder"],
        storage=DocumentStorage(settings.upload_dir),
        settings=settings,
    )
    logger.info("worker_startup")


async def on_shutdown(ctx: dict[Any, Any]) -> None:
    for key in ("http", "app_redis"):
        client = ctx.get(key)
        if client is not None:
            await client.aclose()
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    logger.info("worker_shutdown")


class WorkerSettings(WorkerSettingsBase):
    functions: Sequence[WorkerCoroutine | Function] = (
        func(ping, name="ping"),
        func(
            ingest_document,
            name=INGEST_DOCUMENT_JOB,
            timeout=get_settings().ingestion_job_timeout_seconds,
            max_tries=3,  # re-runs only if the worker dies mid-job; the pipeline is idempotent
        ),
        func(
            run_evaluation,
            name=RUN_EVALUATION_JOB,
            timeout=get_settings().eval_job_timeout_seconds,
            max_tries=1,  # a failed run is marked failed; re-run it from the dashboard
        ),
    )
    on_startup: StartupShutdown | None = on_startup
    on_shutdown: StartupShutdown | None = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 2  # embedding is CPU-bound; avoid oversubscribing the container


def main() -> None:
    configure_logging(get_settings().log_level)
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
