"""Acts list, full section text, IPC -> BNS mapping, and answer feedback."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUserDep, DbSessionDep
from app.schemas.catalog import (
    ActSummary,
    FeedbackRead,
    FeedbackRequest,
    MappingView,
    SectionView,
)
from app.schemas.error import ErrorResponse
from app.services.catalog import CatalogService, FeedbackService

router = APIRouter(tags=["catalog"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}


def get_catalog(session: DbSessionDep) -> CatalogService:
    return CatalogService(session)


CatalogDep = Annotated[CatalogService, Depends(get_catalog)]


@router.get("/acts", response_model=list[ActSummary], summary="Indexed acts with chunk counts")
async def list_acts(_user: CurrentUserDep, catalog: CatalogDep) -> list[ActSummary]:
    return await catalog.list_acts()


@router.get(
    "/sections/{act_code}/{section_number}",
    response_model=SectionView,
    responses=_NOT_FOUND,
    summary="Full text of one section",
)
async def get_section(
    act_code: str, section_number: str, _user: CurrentUserDep, catalog: CatalogDep
) -> SectionView:
    return await catalog.get_section(act_code, section_number)


@router.get(
    "/mapping/ipc/{section}",
    response_model=MappingView,
    responses=_NOT_FOUND,
    summary="BNS section(s) that replaced an IPC section, with both texts",
)
async def ipc_mapping(section: str, _user: CurrentUserDep, catalog: CatalogDep) -> MappingView:
    return await catalog.ipc_mapping(section)


@router.post(
    "/feedback",
    response_model=FeedbackRead,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}},
    summary="Thumbs up/down on one of your answers",
)
async def submit_feedback(
    body: FeedbackRequest, user: CurrentUserDep, session: DbSessionDep
) -> FeedbackRead:
    return await FeedbackService(session).submit(user.id, body)
