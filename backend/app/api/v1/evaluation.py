"""Admin evaluation endpoints: dataset status, start a run (background job), view runs."""

import uuid
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import AdminUserDep, SettingsDep, get_job_queue
from app.core.exceptions import ServiceUnavailableError
from app.db.models import EvalRunStatus
from app.schemas.error import ErrorResponse
from app.schemas.evaluation import DatasetStatus, EvalRunCreated, EvalRunDetail, EvalRunSummary
from app.services.evaluation.runner import EvalConfig
from app.services.evaluation.service import EvaluationService
from app.workers.queue import JobQueue

router = APIRouter(prefix="/eval", tags=["evaluation"])


def get_evaluation_service(request: Request, settings: SettingsDep) -> EvaluationService:
    factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    return EvaluationService(factory, settings)


EvaluationDep = Annotated[EvaluationService, Depends(get_evaluation_service)]
_ERRORS: dict[int | str, dict[str, Any]] = {
    c: {"model": ErrorResponse} for c in (400, 401, 403, 503)
}


@router.get("/dataset", response_model=DatasetStatus, summary="Golden dataset status (admin)")
async def dataset_status(_admin: AdminUserDep, service: EvaluationDep) -> DatasetStatus:
    return DatasetStatus.model_validate(service.dataset_status())


@router.post(
    "/run",
    response_model=EvalRunCreated,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_ERRORS,
    summary="Start an evaluation run in the background (admin)",
)
async def start_run(
    body: EvalConfig,
    _admin: AdminUserDep,
    service: EvaluationDep,
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> EvalRunCreated:
    run_id = await service.create_run(body)
    try:
        await queue.enqueue_evaluation(run_id)
    except Exception as exc:
        raise ServiceUnavailableError("The job queue is unavailable. Please try again.") from exc
    return EvalRunCreated(eval_run_id=run_id, status=EvalRunStatus.PENDING)


@router.get("/runs", response_model=list[EvalRunSummary], summary="Recent evaluation runs (admin)")
async def list_runs(
    _admin: AdminUserDep,
    service: EvaluationDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[EvalRunSummary]:
    return [EvalRunSummary.from_run(run) for run in await service.list_runs(limit)]


@router.get(
    "/runs/{run_id}",
    response_model=EvalRunDetail,
    responses={404: {"model": ErrorResponse}},
    summary="One evaluation run with metrics and per-question results (admin)",
)
async def get_run(run_id: uuid.UUID, _admin: AdminUserDep, service: EvaluationDep) -> EvalRunDetail:
    return EvalRunDetail.from_run(await service.get_run(run_id))
