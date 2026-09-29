"""Value types for retrieval."""

from dataclasses import dataclass, field
from enum import StrEnum

from app.db.models.enums import ActStatus
from app.services.ingestion.types import format_context_header


class RetrievalMode(StrEnum):
    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


class CandidateSource(StrEnum):
    SECTION_REF = "section_ref"  # the query named this section explicitly
    MAPPING = "mapping"  # reached via section_mappings from a referenced section
    SEARCH = "search"  # found by keyword/vector search


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """A chunk as returned from the database (without its embedding)."""

    id: int
    act_code: str
    act_status: ActStatus
    chapter_number: str | None
    chapter_title: str | None
    section_number: str
    section_title: str | None
    subsection: str | None
    text: str
    page_start: int | None
    page_end: int | None

    @property
    def context_header(self) -> str:
        return format_context_header(
            self.act_code,
            self.chapter_number,
            self.chapter_title,
            self.section_number,
            self.section_title,
        )


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """One row from a single search stage."""

    chunk: ChunkRecord
    score: float  # ts_rank_cd for keyword search; cosine similarity for vector search


@dataclass(frozen=True, slots=True)
class SectionRef:
    """A section explicitly referenced in the query, e.g. "IPC 420" -> ("IPC", "420")."""

    act_code: str
    section: str  # base section number, e.g. "318" or "66C"
    subsection: str | None = None  # e.g. "(4)" or "(1)(a)"
    raw: str = ""

    @property
    def label(self) -> str:
        return f"{self.act_code} {self.section}{self.subsection or ''}"


@dataclass(slots=True)
class Candidate:
    """A chunk moving through fusion and re-ranking, with the scores it collected."""

    chunk: ChunkRecord
    source: CandidateSource = CandidateSource.SEARCH
    matched_ref: str | None = None  # e.g. "IPC 420" (or "IPC 420 -> BNS 318" for mappings)
    keyword_rank: int | None = None
    keyword_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


@dataclass(slots=True)
class RetrievalResult:
    """Final results plus a per-stage trace (used by the debug endpoint and evaluation)."""

    query: str
    mode: RetrievalMode
    search_queries: list[str]
    act_filter: list[str] | None
    section_refs: list[SectionRef]
    direct: list[Candidate]
    keyword: dict[str, list[ChunkHit]] = field(default_factory=dict)
    vector: dict[str, list[ChunkHit]] = field(default_factory=dict)
    fused: list[Candidate] = field(default_factory=list)
    reranked: list[Candidate] = field(default_factory=list)
    final: list[Candidate] = field(default_factory=list)
    # One candidate per section of `final`, with the section's full text (answer context).
    context: list[Candidate] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
