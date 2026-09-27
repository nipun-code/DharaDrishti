"""POST /query and /query/stream request/response schemas (SPEC §9)."""

import uuid

from pydantic import BaseModel, Field

from app.db.models.enums import ActStatus
from app.schemas.documents import ActCode
from app.services.retrieval.types import RetrievalMode

DISCLAIMER = (
    "This is legal information from bare acts, not legal advice. "
    "Consult a qualified advocate for your situation."
)


class QueryRequest(BaseModel):
    # Generous hard cap here; the configurable length guardrail runs in the pipeline.
    query: str = Field(min_length=1, max_length=10_000)
    acts: list[ActCode] | None = Field(default=None, max_length=20)
    mode: RetrievalMode = RetrievalMode.HYBRID_RERANK
    top_k: int | None = Field(default=None, ge=1, le=10)


class Citation(BaseModel):
    n: int
    act: str
    act_status: ActStatus
    section_number: str
    section_title: str | None
    page_start: int | None
    snippet: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    refused: bool
    refusal_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER
    latency_ms: int
    cache_hit: bool = False
    query_log_id: uuid.UUID | None = None
