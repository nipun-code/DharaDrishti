"""Retrieval debugging (admin only): every stage of hybrid retrieval with ranks and scores."""

from fastapi import APIRouter

from app.api.deps import AdminUserDep, RetrieverDep
from app.schemas.error import ErrorResponse
from app.schemas.retrieval import RetrievalDebugRequest, RetrievalDebugResponse

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post(
    "/debug",
    response_model=RetrievalDebugResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Run retrieval and return results from each stage (admin)",
)
async def debug_retrieval(
    body: RetrievalDebugRequest, _admin: AdminUserDep, retriever: RetrieverDep
) -> RetrievalDebugResponse:
    result = await retriever.retrieve(
        body.query,
        acts=body.acts,
        mode=body.mode,
        top_k=body.top_k,
        extra_queries=body.extra_queries,
    )
    return RetrievalDebugResponse.from_result(result)
