"""Evaluation API schemas (SPEC §9: POST /eval/run, GET /eval/runs, GET /eval/runs/{id})."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.db.models import EvalRun, EvalRunStatus


class DatasetStatus(BaseModel):
    path: str
    exists: bool
    questions: int
    by_category: dict[str, int]
    errors: list[str]


class EvalRunCreated(BaseModel):
    eval_run_id: uuid.UUID
    status: EvalRunStatus


class EvalRunSummary(BaseModel):
    id: uuid.UUID
    status: EvalRunStatus
    progress: int
    config: dict[str, Any]
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    # Headline numbers per mode, for the history list.
    headline: dict[str, dict[str, float | None]]

    @classmethod
    def from_run(cls, run: EvalRun) -> "EvalRunSummary":
        modes = (run.metrics or {}).get("modes", {})
        return cls(
            id=run.id,
            status=run.status,
            progress=run.progress,
            config=run.config,
            error=run.error,
            created_at=run.created_at,
            finished_at=run.finished_at,
            headline={
                mode: {k: values.get(k) for k in ("recall_at_5", "mrr", "faithfulness")}
                for mode, values in modes.items()
            },
        )


class EvalRunDetail(EvalRunSummary):
    metrics: dict[str, Any] | None
    per_question: list[dict[str, Any]] | None

    @classmethod
    def from_run(cls, run: EvalRun) -> "EvalRunDetail":
        return cls(
            **EvalRunSummary.from_run(run).model_dump(),
            metrics=run.metrics,
            per_question=run.per_question,
        )
