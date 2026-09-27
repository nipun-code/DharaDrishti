"""Document upload / status schemas."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

from app.db.models.enums import ActStatus, DocumentStatus


def _upper_strip(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


ActCode = Annotated[
    str,
    BeforeValidator(_upper_strip),
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,31}$"),
]


class ActUpsert(BaseModel):
    """Act metadata sent with an upload. Creates the act if new, otherwise updates given fields."""

    act_short_code: ActCode = Field(description="e.g. BNS, BNSS, BSA, IPC, ITA")
    act_full_name: str | None = Field(
        default=None, min_length=3, max_length=255, description="Required for a new act."
    )
    act_year: int | None = Field(
        default=None, ge=1800, le=2100, description="Required for a new act."
    )
    act_status: ActStatus | None = Field(
        default=None, description="Defaults to in_force for a new act."
    )


class DocumentRead(BaseModel):
    id: uuid.UUID
    act_short_code: str
    filename: str
    status: DocumentStatus
    progress: int = Field(ge=0, le=100)
    error: str | None
    pages: int | None
    chunks_count: int
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus


class DocumentList(BaseModel):
    items: list[DocumentRead]
    limit: int
    offset: int
