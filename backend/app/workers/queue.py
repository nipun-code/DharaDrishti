"""Enqueueing background jobs (kept apart from worker.py so the API never imports the worker)."""

import uuid
from typing import Protocol

from arq.connections import ArqRedis

INGEST_DOCUMENT_JOB = "ingest_document"
RUN_EVALUATION_JOB = "run_evaluation"


class JobQueue(Protocol):
    async def enqueue_ingestion(self, document_id: uuid.UUID) -> None: ...

    async def enqueue_evaluation(self, eval_run_id: uuid.UUID) -> None: ...


class ArqJobQueue:
    def __init__(self, redis: ArqRedis) -> None:
        self._redis = redis

    async def enqueue_ingestion(self, document_id: uuid.UUID) -> None:
        # A deterministic job id makes double-enqueueing the same document a no-op.
        await self._redis.enqueue_job(
            INGEST_DOCUMENT_JOB, str(document_id), _job_id=f"ingest:{document_id}"
        )

    async def enqueue_evaluation(self, eval_run_id: uuid.UUID) -> None:
        await self._redis.enqueue_job(
            RUN_EVALUATION_JOB, str(eval_run_id), _job_id=f"eval:{eval_run_id}"
        )
