"""Liveness and readiness probes. Mounted at the root (/health/*) so orchestrators can reach them
without knowing the API version prefix."""

from fastapi import APIRouter, Response, status

from app.api.deps import HealthServiceDep
from app.schemas.health import LivenessResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse, summary="Process is up")
async def live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Process can serve traffic (database and Redis reachable)",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(response: Response, service: HealthServiceDep) -> ReadinessResponse:
    report = await service.check_readiness()
    if not report.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
