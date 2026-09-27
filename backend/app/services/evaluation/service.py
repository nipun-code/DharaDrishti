"""Evaluation runs: dataset status, run lifecycle and persistence (eval_runs).

Used by the admin API (create + enqueue), the ARQ worker (execute) and the CLI (both, inline).
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models import EvalRun, EvalRunStatus
from app.services.cache.exact import AnswerCache
from app.services.evaluation.dataset import DatasetError, GoldenItem, category_counts, load_golden
from app.services.evaluation.runner import EvalConfig, EvaluationRunner
from app.services.ingestion.embedder import SentenceTransformerEmbedder
from app.services.llm.fallback import LLMClient
from app.services.query.store import PostgresQueryStore
from app.services.retrieval.hybrid import HybridRetriever, QueryEmbedder
from app.services.retrieval.reranker import CrossEncoderReranker, Reranker
from app.services.retrieval.search import PostgresSearchBackend

logger = logging.getLogger(__name__)


def build_runner(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    embedder: QueryEmbedder,
    reranker: Reranker,
    llm: LLMClient,
    redis: Redis | None = None,
) -> EvaluationRunner:
    retriever = HybridRetriever(
        PostgresSearchBackend(session_factory, ef_search=settings.hnsw_ef_search),
        embedder,
        reranker,
        settings,
    )
    cache = AnswerCache(redis, ttl_seconds=settings.cache_ttl_seconds) if redis else None
    return EvaluationRunner(
        settings=settings,
        retriever=retriever,
        llm=llm,
        store=PostgresQueryStore(session_factory),
        cache=cache,
    )


class EvaluationService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    # ---------------------------------------------------------------- dataset
    def load_dataset(self) -> list[GoldenItem]:
        try:
            return load_golden(self._settings.golden_dataset_path)
        except DatasetError as exc:
            count = len(exc.errors)
            message = (
                exc.errors[0]
                if count == 1
                else f"The golden dataset has {count} problems. First: {exc.errors[0]}"
            )
            raise BadRequestError(message, details={"errors": exc.errors[:20]}) from exc

    def dataset_status(self) -> dict[str, Any]:
        path = self._settings.golden_dataset_path
        status: dict[str, Any] = {
            "path": str(path),
            "exists": path.is_file(),
            "questions": 0,
            "by_category": {},
            "errors": [],
        }
        if not status["exists"]:
            return status
        try:
            items = load_golden(path)
        except DatasetError as exc:
            status["errors"] = exc.errors[:20]
            return status
        status.update(questions=len(items), by_category=category_counts(items))
        return status

    # ---------------------------------------------------------------- runs
    async def create_run(self, config: EvalConfig) -> uuid.UUID:
        self.load_dataset()  # fail fast with line-numbered errors, before queueing
        async with self._session_factory() as session:
            run = EvalRun(config=config.model_dump(mode="json"))
            session.add(run)
            await session.commit()
            return run.id

    async def list_runs(self, limit: int = 20) -> list[EvalRun]:
        async with self._session_factory() as session:
            stmt = select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit)
            return list(await session.scalars(stmt))

    async def get_run(self, run_id: uuid.UUID) -> EvalRun:
        async with self._session_factory() as session:
            run = await session.get(EvalRun, run_id)
        if run is None:
            raise NotFoundError("Evaluation run not found.")
        return run

    async def _update(self, run_id: uuid.UUID, **values: Any) -> None:
        async with self._session_factory() as session:
            await session.execute(update(EvalRun).where(EvalRun.id == run_id).values(**values))
            await session.commit()

    async def execute(self, run_id: uuid.UUID, runner: EvaluationRunner) -> dict[str, Any]:
        run = await self.get_run(run_id)
        if run.status == EvalRunStatus.COMPLETED:
            return run.metrics or {}
        config = EvalConfig.model_validate(run.config)
        await self._update(run_id, status=EvalRunStatus.RUNNING, progress=0, error=None)
        last = -1

        async def progress(percent: int) -> None:
            nonlocal last
            if percent != last:
                last = percent
                await self._update(run_id, progress=percent)

        try:
            report = await runner.run(self.load_dataset(), config, progress)
        except Exception as exc:
            logger.exception("eval_run_failed", extra={"eval_run_id": str(run_id)})
            message = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
            await self._update(
                run_id,
                status=EvalRunStatus.FAILED,
                error=message[:2000],
                finished_at=datetime.now(UTC),
            )
            raise
        await self._update(
            run_id,
            status=EvalRunStatus.COMPLETED,
            progress=100,
            metrics=report.metrics,
            per_question=report.per_question,
            finished_at=datetime.now(UTC),
        )
        logger.info("eval_run_completed", extra={"eval_run_id": str(run_id)})
        return report.metrics


async def run_evaluation_cli(
    settings: Settings, config: EvalConfig
) -> tuple[uuid.UUID, dict[str, Any]]:
    """Inline run for the CLI: builds real models/LLM, creates and executes an eval run."""
    from app.db.redis import create_redis  # noqa: PLC0415
    from app.db.session import create_engine, create_session_factory  # noqa: PLC0415
    from app.services.llm.factory import build_llm  # noqa: PLC0415

    engine = create_engine(settings)
    redis = create_redis(settings) if config.use_cache else None
    async with httpx.AsyncClient() as http:
        try:
            factory = create_session_factory(engine)
            service = EvaluationService(factory, settings)
            runner = build_runner(
                settings,
                factory,
                embedder=SentenceTransformerEmbedder(
                    settings.embedding_model_name,
                    device=settings.embedding_device,
                    query_instruction=settings.embedding_query_instruction,
                ),
                reranker=CrossEncoderReranker(
                    settings.reranker_model_name, device=settings.embedding_device
                ),
                llm=build_llm(settings, http),
                redis=redis,
            )
            run_id = await service.create_run(config)
            return run_id, await service.execute(run_id, runner)
        finally:
            if redis is not None:
                await redis.aclose()
            await engine.dispose()
