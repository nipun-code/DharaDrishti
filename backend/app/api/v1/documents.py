"""Document upload and ingestion status. Uploading and managing documents is admin-only."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.deps import AdminUserDep, CurrentUserDep, DocumentServiceDep
from app.db.models.enums import ActStatus
from app.schemas.documents import (
    ActUpsert,
    DocumentList,
    DocumentRead,
    DocumentUploadResponse,
)
from app.schemas.error import ErrorResponse

router = APIRouter(prefix="/documents", tags=["documents"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 401, 403, 409, 413, 415, 503)
}


def act_metadata_form(
    act_short_code: Annotated[str, Form(description="e.g. BNS, BNSS, BSA, IPC, ITA")],
    act_full_name: Annotated[str | None, Form(description="Required for a new act.")] = None,
    act_year: Annotated[int | None, Form(description="Required for a new act.")] = None,
    act_status: Annotated[ActStatus | None, Form(description="Default in_force.")] = None,
) -> ActUpsert:
    """Individual form fields (a Pydantic form model can't be combined with a File part)."""
    try:
        return ActUpsert(
            act_short_code=act_short_code,
            act_full_name=act_full_name,
            act_year=act_year,
            act_status=act_status,
        )
    except ValidationError as exc:
        raise RequestValidationError(
            [{**err, "loc": ("body", *err["loc"])} for err in exc.errors()]
        ) from exc


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadResponse,
    responses=_ERRORS,
    summary="Upload a bare-act PDF for ingestion (admin)",
)
async def upload_document(
    _admin: AdminUserDep,
    file: Annotated[UploadFile, File(description="Bare-act PDF")],
    act: Annotated[ActUpsert, Depends(act_metadata_form)],
    service: DocumentServiceDep,
) -> DocumentUploadResponse:
    document = await service.upload(file, file.filename, file.content_type, act)
    return DocumentUploadResponse(document_id=document.id, status=document.status)


@router.get("", response_model=DocumentList, summary="List uploaded documents (admin)")
async def list_documents(
    _admin: AdminUserDep,
    service: DocumentServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    return DocumentList(
        items=await service.list(limit=limit, offset=offset), limit=limit, offset=offset
    )


@router.get(
    "/{document_id}",
    response_model=DocumentRead,
    responses={404: {"model": ErrorResponse}},
    summary="Ingestion status and progress of a document",
)
async def get_document(
    document_id: uuid.UUID, _user: CurrentUserDep, service: DocumentServiceDep
) -> DocumentRead:
    return await service.get(document_id)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Delete a document and its chunks (admin)",
)
async def delete_document(
    document_id: uuid.UUID, _admin: AdminUserDep, service: DocumentServiceDep
) -> None:
    await service.delete(document_id)
