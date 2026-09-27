"""Acts, section text and IPC -> BNS mapping schemas (SPEC §9)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models.enums import ActStatus


class ActSummary(BaseModel):
    short_code: str
    full_name: str
    year: int
    status: ActStatus
    chunks_count: int


class SectionView(BaseModel):
    act: str
    act_name: str
    act_status: ActStatus
    section_number: str
    section_title: str | None
    chapter_number: str | None
    chapter_title: str | None
    text: str
    page_start: int | None
    page_end: int | None


class MappingTarget(BaseModel):
    to_act: str
    to_section: str
    note: str | None
    section: SectionView | None = Field(description="Target text, if that act is ingested.")


class MappingView(BaseModel):
    from_act: str
    from_section: str
    source: SectionView | None = Field(description="Old section text, if ingested.")
    targets: list[MappingTarget]


class FeedbackRequest(BaseModel):
    query_log_id: uuid.UUID
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackRead(BaseModel):
    id: int
    query_log_id: uuid.UUID
    rating: int
    comment: str | None
    created_at: datetime
