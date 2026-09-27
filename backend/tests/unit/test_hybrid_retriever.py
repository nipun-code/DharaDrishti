"""HybridRetriever orchestration with an in-memory search backend (no database)."""

from collections.abc import Sequence

import pytest

from app.core.config import Settings
from app.db.models.enums import ActStatus
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.types import (
    CandidateSource,
    ChunkHit,
    ChunkRecord,
    RetrievalMode,
)
from tests.conftest import FakeQueryEmbedder, FakeReranker


def record(chunk_id: int, text: str, act: str = "BNS", section: str | None = None) -> ChunkRecord:
    return ChunkRecord(
        id=chunk_id,
        act_code=act,
        act_status=ActStatus.IN_FORCE,
        chapter_number=None,
        chapter_title=None,
        section_number=section or str(chunk_id),
        section_title=f"Heading {chunk_id}",
        subsection=None,
        text=text,
        page_start=1,
        page_end=1,
    )


class FakeBackend:
    def __init__(self) -> None:
        self.keyword_results: dict[str, list[ChunkRecord]] = {}
        self.vector_results: list[ChunkRecord] = []
        self.sections: dict[tuple[str, str], list[ChunkRecord]] = {}
        self.mapping_rows: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self.keyword_calls: list[tuple[str, Sequence[str] | None, int]] = []
        self.vector_calls = 0
        self.section_calls: list[tuple[str, str, str | None]] = []

    async def keyword(
        self, query: str, act_codes: Sequence[str] | None, limit: int
    ) -> list[ChunkHit]:
        self.keyword_calls.append((query, act_codes, limit))
        return [
            ChunkHit(c, 1.0 / (i + 1)) for i, c in enumerate(self.keyword_results.get(query, []))
        ]

    async def vector(
        self, embedding: Sequence[float], act_codes: Sequence[str] | None, limit: int
    ) -> list[ChunkHit]:
        self.vector_calls += 1
        return [ChunkHit(c, 0.9 - i / 10) for i, c in enumerate(self.vector_results[:limit])]

    async def section(
        self, act_code: str, section: str, subsection: str | None, limit: int
    ) -> list[ChunkRecord]:
        self.section_calls.append((act_code, section, subsection))
        return self.sections.get((act_code, section), [])[:limit]

    async def mappings(self, from_act: str, section: str) -> list[tuple[str, str]]:
        return self.mapping_rows.get((from_act, section), [])


A = record(1, "alpha widget text")
B = record(2, "beta gadget text")
C = record(3, "gamma widget gadget text")
D = record(4, "delta unrelated")


@pytest.fixture
def backend() -> FakeBackend:
    fake = FakeBackend()
    fake.keyword_results["widget"] = [A, C]
    fake.vector_results = [C, B, D]
    return fake


@pytest.fixture
def embedder() -> FakeQueryEmbedder:
    return FakeQueryEmbedder()


@pytest.fixture
def reranker() -> FakeReranker:
    return FakeReranker()


@pytest.fixture
def retriever(
    backend: FakeBackend, embedder: FakeQueryEmbedder, reranker: FakeReranker, settings: Settings
) -> HybridRetriever:
    return HybridRetriever(backend, embedder, reranker, settings)


def ids(candidates: Sequence[object]) -> list[int]:
    return [c.chunk.id for c in candidates]  # type: ignore[attr-defined]


# ---------------------------------------------------------------- modes
async def test_keyword_mode_skips_embedding(
    retriever: HybridRetriever, backend: FakeBackend, embedder: FakeQueryEmbedder
) -> None:
    result = await retriever.retrieve("widget", mode=RetrievalMode.KEYWORD)

    assert ids(result.final) == [1, 3]
    assert embedder.calls == []
    assert backend.vector_calls == 0
    assert result.vector == {}


async def test_vector_mode_skips_keyword(retriever: HybridRetriever, backend: FakeBackend) -> None:
    result = await retriever.retrieve("widget", mode=RetrievalMode.VECTOR)

    assert ids(result.final) == [3, 2, 4]
    assert backend.keyword_calls == []


async def test_hybrid_fuses_with_rrf(retriever: HybridRetriever, reranker: FakeReranker) -> None:
    result = await retriever.retrieve("widget", mode=RetrievalMode.HYBRID)

    # C is in both lists (keyword #2, vector #1) so it wins; then A (kw #1), B (vec #2), D.
    assert ids(result.final) == [3, 1, 2, 4]
    top = result.final[0]
    assert (top.keyword_rank, top.vector_rank) == (2, 1)
    assert top.rrf_score == pytest.approx(1 / 62 + 1 / 61)
    assert reranker.calls == []
    assert result.reranked == []


async def test_hybrid_rerank_reorders_by_cross_encoder(
    retriever: HybridRetriever, reranker: FakeReranker
) -> None:
    result = await retriever.retrieve("gadget", mode=RetrievalMode.HYBRID_RERANK, top_k=2)

    # Only vector hits (no keyword results for "gadget"); reranker prefers passages with "gadget".
    assert set(ids(result.final)) == {2, 3}
    assert all(c.rerank_score == 1.0 for c in result.final)
    assert reranker.calls == [("gadget", 3)]
    assert "rerank" in result.timings_ms


async def test_rerank_pool_limited_to_rerank_candidates(
    backend: FakeBackend, embedder: FakeQueryEmbedder, reranker: FakeReranker, settings: Settings
) -> None:
    backend.vector_results = [record(i, f"text {i}") for i in range(10, 40)]
    retriever = HybridRetriever(
        backend, embedder, reranker, settings.model_copy(update={"rerank_candidates": 7})
    )

    result = await retriever.retrieve("anything")

    assert reranker.calls == [("anything", 7)]
    assert len(result.reranked) == 7
    assert len(result.final) == settings.retrieval_top_k


async def test_top_k_default_and_override(retriever: HybridRetriever, settings: Settings) -> None:
    assert len((await retriever.retrieve("widget", mode=RetrievalMode.HYBRID, top_k=1)).final) == 1
    default = await retriever.retrieve("widget", mode=RetrievalMode.HYBRID)
    assert len(default.final) == min(4, settings.retrieval_top_k)


# ---------------------------------------------------------------- queries & filters
async def test_extra_queries_searched_and_deduplicated(
    retriever: HybridRetriever, backend: FakeBackend, embedder: FakeQueryEmbedder
) -> None:
    backend.keyword_results["gadget"] = [B]

    result = await retriever.retrieve(
        "widget", mode=RetrievalMode.HYBRID, extra_queries=["gadget", "  Widget ", "gadget"]
    )

    assert result.search_queries == ["widget", "gadget"]
    assert [q for q, _, _ in backend.keyword_calls] == ["widget", "gadget"]
    assert embedder.calls == [["widget", "gadget"]]  # one batched embedding call
    assert set(result.keyword) == {"widget", "gadget"}


async def test_act_filter_normalized_and_passed_through(
    retriever: HybridRetriever, backend: FakeBackend
) -> None:
    result = await retriever.retrieve(
        "widget", acts=["ipc", "bns", "IPC"], mode=RetrievalMode.KEYWORD
    )

    assert result.act_filter == ["BNS", "IPC"]
    assert backend.keyword_calls[0][1] == ["BNS", "IPC"]


# ---------------------------------------------------------------- direct lookup
async def test_section_reference_results_come_first_without_duplicates(
    retriever: HybridRetriever, backend: FakeBackend
) -> None:
    old = record(50, "old section text", act="IPC", section="9001")
    backend.sections[("IPC", "9001")] = [old]
    backend.sections[("BNS", "3")] = [C]
    backend.mapping_rows[("IPC", "9001")] = [("BNS", "3")]
    backend.keyword_results["IPC 9001 widget"] = [A, C]

    result = await retriever.retrieve("IPC 9001 widget", mode=RetrievalMode.HYBRID)

    assert [r.label for r in result.section_refs] == ["IPC 9001"]
    assert ids(result.direct) == [50, 3]
    assert result.direct[0].source == CandidateSource.SECTION_REF
    assert result.direct[1].source == CandidateSource.MAPPING
    assert result.direct[1].matched_ref == "IPC 9001 -> BNS 3"
    assert ids(result.final)[:2] == [50, 3]
    assert ids(result.final).count(3) == 1  # C not repeated from search results


async def test_mapping_to_subsection_looks_up_base_section(
    retriever: HybridRetriever, backend: FakeBackend
) -> None:
    backend.mapping_rows[("IPC", "9001")] = [("BNS", "9002(4)")]

    await retriever.retrieve("IPC 9001", mode=RetrievalMode.KEYWORD)

    assert ("BNS", "9002", "(4)") in backend.section_calls


async def test_number_of_section_refs_is_capped(
    backend: FakeBackend, embedder: FakeQueryEmbedder, reranker: FakeReranker, settings: Settings
) -> None:
    retriever = HybridRetriever(
        backend, embedder, reranker, settings.model_copy(update={"max_section_refs": 2})
    )

    result = await retriever.retrieve("IPC 101, 102, 103 and 104", mode=RetrievalMode.KEYWORD)

    assert [r.section for r in result.section_refs] == ["101", "102"]


async def test_no_results_is_not_an_error(retriever: HybridRetriever) -> None:
    result = await retriever.retrieve("nothing matches", mode=RetrievalMode.KEYWORD)

    assert result.final == []
    assert result.fused == []
    assert result.timings_ms["total"] >= 0


async def test_on_stage_reports_reranking_only_when_it_happens(retriever: HybridRetriever) -> None:
    stages: list[str] = []

    await retriever.retrieve("widget", mode=RetrievalMode.HYBRID, on_stage=stages.append)
    await retriever.retrieve("widget", mode=RetrievalMode.HYBRID_RERANK, on_stage=stages.append)

    assert stages == ["reranking"]
