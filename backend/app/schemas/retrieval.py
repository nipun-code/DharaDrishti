"""Retrieval debug endpoint schemas."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.db.models.enums import ActStatus
from app.schemas.documents import ActCode
from app.services.retrieval.types import (
    Candidate,
    CandidateSource,
    ChunkHit,
    RetrievalMode,
    RetrievalResult,
)

QueryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
_SNIPPET_CHARS = 300


class RetrievalDebugRequest(BaseModel):
    query: QueryText
    acts: list[ActCode] | None = Field(
        default=None, max_length=20, description="Act codes; default = all in-force acts."
    )
    mode: RetrievalMode = RetrievalMode.HYBRID_RERANK
    top_k: int | None = Field(default=None, ge=1, le=50)
    extra_queries: list[QueryText] = Field(
        default_factory=list,
        max_length=3,
        description="Extra search phrasings (stand-in for query rewriting).",
    )


class SectionRefOut(BaseModel):
    act: str
    section: str
    subsection: str | None
    label: str


class ChunkOut(BaseModel):
    chunk_id: int
    act: str
    act_status: ActStatus
    section_number: str
    section_title: str | None
    subsection: str | None
    chapter: str | None
    page_start: int | None
    page_end: int | None
    snippet: str


class StageHitOut(ChunkOut):
    rank: int
    score: float


class CandidateOut(ChunkOut):
    source: CandidateSource
    matched_ref: str | None
    keyword_rank: int | None
    keyword_score: float | None
    vector_rank: int | None
    vector_score: float | None
    rrf_score: float | None
    rerank_score: float | None


class RetrievalDebugResponse(BaseModel):
    query: str
    mode: RetrievalMode
    search_queries: list[str]
    act_filter: list[str] | None
    section_refs: list[SectionRefOut]
    direct: list[CandidateOut]
    keyword: dict[str, list[StageHitOut]]
    vector: dict[str, list[StageHitOut]]
    fused: list[CandidateOut]
    reranked: list[CandidateOut]
    final: list[CandidateOut]
    timings_ms: dict[str, float]

    @classmethod
    def from_result(cls, result: RetrievalResult) -> "RetrievalDebugResponse":
        return cls(
            query=result.query,
            mode=result.mode,
            search_queries=result.search_queries,
            act_filter=result.act_filter,
            section_refs=[
                SectionRefOut(
                    act=r.act_code, section=r.section, subsection=r.subsection, label=r.label
                )
                for r in result.section_refs
            ],
            direct=[_candidate(c) for c in result.direct],
            keyword={q: _hits(h) for q, h in result.keyword.items()},
            vector={q: _hits(h) for q, h in result.vector.items()},
            fused=[_candidate(c) for c in result.fused],
            reranked=[_candidate(c) for c in result.reranked],
            final=[_candidate(c) for c in result.final],
            timings_ms=result.timings_ms,
        )


def _chunk_fields(c: Candidate | ChunkHit) -> dict[str, object]:
    chunk = c.chunk
    text = " ".join(chunk.text.split())
    chapter = None
    if chunk.chapter_number:
        chapter = chunk.chapter_number + (f": {chunk.chapter_title}" if chunk.chapter_title else "")
    return {
        "chunk_id": chunk.id,
        "act": chunk.act_code,
        "act_status": chunk.act_status,
        "section_number": chunk.section_number,
        "section_title": chunk.section_title,
        "subsection": chunk.subsection,
        "chapter": chapter,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "snippet": text if len(text) <= _SNIPPET_CHARS else text[:_SNIPPET_CHARS] + "…",
    }


def _hits(hits: list[ChunkHit]) -> list[StageHitOut]:
    return [
        StageHitOut(**_chunk_fields(hit), rank=rank, score=hit.score)  # type: ignore[arg-type]
        for rank, hit in enumerate(hits, start=1)
    ]


def _candidate(c: Candidate) -> CandidateOut:
    return CandidateOut(
        **_chunk_fields(c),  # type: ignore[arg-type]
        source=c.source,
        matched_ref=c.matched_ref,
        keyword_rank=c.keyword_rank,
        keyword_score=c.keyword_score,
        vector_rank=c.vector_rank,
        vector_score=c.vector_score,
        rrf_score=c.rrf_score,
        rerank_score=c.rerank_score,
    )
