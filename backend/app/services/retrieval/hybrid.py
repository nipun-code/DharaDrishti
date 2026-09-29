"""Hybrid retrieval (SPEC §7 steps 3 and 5-7).

    1. Section references in the query ("IPC 420") are looked up directly, plus their mapped
       sections (IPC -> BNS via section_mappings). These always go first in the results.
    2. For every search query: keyword search and vector search, run concurrently.
    3. Reciprocal Rank Fusion over all rankings the mode uses; de-duplicated.
    4. hybrid_rerank only: the top fused candidates are re-scored by the cross-encoder, and
       the final order blends that with the fused order (RRF of the two rankings).
    5. Answer context: each section in the final list is re-read in full (all its pieces).

Modes: keyword | vector | hybrid (RRF) | hybrid_rerank (RRF + cross-encoder, default).
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, TypeVar

from app.core.config import Settings
from app.services.retrieval.expansion import expand_sections
from app.services.retrieval.fusion import reciprocal_rank_fusion
from app.services.retrieval.reranker import Reranker, text_windows
from app.services.retrieval.search import SearchBackend
from app.services.retrieval.section_lookup import parse_section_refs, strip_act_names
from app.services.retrieval.types import (
    Candidate,
    CandidateSource,
    ChunkHit,
    RetrievalMode,
    RetrievalResult,
    SectionRef,
)

T = TypeVar("T")
_SUBSECTION_RE = re.compile(r"^(?P<base>[^()]+)(?P<sub>\(.*\))?$")


class QueryEmbedder(Protocol):
    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]: ...


async def _timed(timings: dict[str, float], name: str, awaitable: Awaitable[T]) -> T:
    started = time.perf_counter()
    try:
        return await awaitable
    finally:
        timings[name] = round((time.perf_counter() - started) * 1000, 2)


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        cleaned = " ".join(value.split())
        if cleaned and cleaned.lower() not in {s.lower() for s in seen}:
            seen[cleaned] = None
    return list(seen)


class HybridRetriever:
    def __init__(
        self,
        backend: SearchBackend,
        embedder: QueryEmbedder,
        reranker: Reranker,
        settings: Settings,
    ) -> None:
        self._backend = backend
        self._embedder = embedder
        self._reranker = reranker
        self._settings = settings

    async def retrieve(
        self,
        query: str,
        *,
        acts: Sequence[str] | None = None,
        mode: RetrievalMode = RetrievalMode.HYBRID_RERANK,
        top_k: int | None = None,
        extra_queries: Sequence[str] = (),
        on_stage: Callable[[str], None] | None = None,
    ) -> RetrievalResult:
        """`extra_queries` are additional search phrasings (e.g. from query rewriting);
        section references are only taken from the user's own `query`. `on_stage` is told
        when a slow stage starts ("reranking"), for live progress in the UI."""
        started = time.perf_counter()
        top_k = top_k or self._settings.retrieval_top_k
        act_codes = sorted({a.upper() for a in acts}) if acts else None
        queries = _dedupe([query, *extra_queries])
        refs = parse_section_refs(query)[: self._settings.max_section_refs]
        result = RetrievalResult(
            query=query,
            mode=mode,
            search_queries=queries,
            act_filter=act_codes,
            section_refs=refs,
            direct=[],
        )
        timings = result.timings_ms

        direct, (keyword, vector) = await asyncio.gather(
            _timed(timings, "direct_lookup", self._direct_lookup(refs)),
            self._search(queries, act_codes, mode, timings),
        )
        result.direct = direct
        result.keyword = dict(zip(queries, keyword, strict=False)) if keyword else {}
        result.vector = dict(zip(queries, vector, strict=False)) if vector else {}

        direct_ids = {c.chunk.id for c in direct}
        result.fused = [c for c in self._fuse(keyword, vector) if c.chunk.id not in direct_ids]

        if mode == RetrievalMode.HYBRID_RERANK and result.fused:
            pool = result.fused[: self._settings.rerank_candidates]
            if on_stage:
                on_stage("reranking")
            result.reranked = await _timed(timings, "rerank", self._rerank(query, pool))
            ranked = result.reranked
        else:
            ranked = result.fused
        result.final = [*direct, *ranked[:top_k]]
        max_pieces = self._settings.section_context_max_chunks
        if max_pieces and result.final:
            result.context = await _timed(
                timings, "section_context", expand_sections(self._backend, result.final, max_pieces)
            )
        else:
            result.context = list(result.final)
        timings["total"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    # ---------------------------------------------------------------- stages
    async def _search(
        self,
        queries: list[str],
        act_codes: list[str] | None,
        mode: RetrievalMode,
        timings: dict[str, float],
    ) -> tuple[list[list[ChunkHit]], list[list[ChunkHit]]]:
        limit = self._settings.retrieval_candidates

        async def keyword_branch() -> list[list[ChunkHit]]:
            if mode == RetrievalMode.VECTOR:
                return []
            # Act names are for the act filter, not the text match (see strip_act_names).
            phrases = [strip_act_names(q) for q in queries]
            return list(
                await asyncio.gather(*(self._backend.keyword(q, act_codes, limit) for q in phrases))
            )

        async def vector_branch() -> list[list[ChunkHit]]:
            if mode == RetrievalMode.KEYWORD:
                return []
            vectors = await _timed(
                timings, "embed_query", asyncio.to_thread(self._embedder.embed_queries, queries)
            )
            return list(
                await asyncio.gather(*(self._backend.vector(v, act_codes, limit) for v in vectors))
            )

        keyword, vector = await asyncio.gather(
            _timed(timings, "keyword_search", keyword_branch()),
            _timed(timings, "vector_branch", vector_branch()),
        )
        return keyword, vector

    async def _direct_lookup(self, refs: Sequence[SectionRef]) -> list[Candidate]:
        if not refs:
            return []
        limit = self._settings.section_lookup_max_chunks
        per_ref = await asyncio.gather(*(self._lookup_ref(ref, limit) for ref in refs))
        seen: set[int] = set()
        ordered: list[Candidate] = []
        for candidates in per_ref:
            for candidate in candidates:
                if candidate.chunk.id not in seen:
                    seen.add(candidate.chunk.id)
                    ordered.append(candidate)
        return ordered

    async def _lookup_ref(self, ref: SectionRef, limit: int) -> list[Candidate]:
        own, targets = await asyncio.gather(
            self._backend.section(ref.act_code, ref.section, ref.subsection, limit),
            self._backend.mappings(ref.act_code, ref.section),
        )
        candidates = [
            Candidate(chunk=chunk, source=CandidateSource.SECTION_REF, matched_ref=ref.label)
            for chunk in own
        ]
        mapped = await asyncio.gather(
            *(self._lookup_mapping_target(ref, act, section, limit) for act, section in targets)
        )
        for group in mapped:
            candidates.extend(group)
        return candidates

    async def _lookup_mapping_target(
        self, ref: SectionRef, to_act: str, to_section: str, limit: int
    ) -> list[Candidate]:
        match = _SUBSECTION_RE.match(to_section)
        base, sub = (match.group("base"), match.group("sub")) if match else (to_section, None)
        chunks = await self._backend.section(to_act, base, sub, limit)
        return [
            Candidate(
                chunk=chunk,
                source=CandidateSource.MAPPING,
                matched_ref=f"{ref.label} -> {to_act} {to_section}",
            )
            for chunk in chunks
        ]

    def _fuse(self, keyword: list[list[ChunkHit]], vector: list[list[ChunkHit]]) -> list[Candidate]:
        candidates: dict[int, Candidate] = {}
        for lists, kind in ((keyword, "keyword"), (vector, "vector")):
            for hits in lists:
                for rank, hit in enumerate(hits, start=1):
                    cand = candidates.setdefault(hit.chunk.id, Candidate(chunk=hit.chunk))
                    if kind == "keyword" and (
                        cand.keyword_rank is None or rank < cand.keyword_rank
                    ):
                        cand.keyword_rank, cand.keyword_score = rank, hit.score
                    if kind == "vector" and (cand.vector_rank is None or rank < cand.vector_rank):
                        cand.vector_rank, cand.vector_score = rank, hit.score
        rankings = [[hit.chunk.id for hit in hits] for hits in (*keyword, *vector)]
        fused: list[Candidate] = []
        for chunk_id, score in reciprocal_rank_fusion(rankings, k=self._settings.rrf_k):
            candidates[chunk_id].rrf_score = score
            fused.append(candidates[chunk_id])
        return fused

    async def _rerank(self, query: str, pool: list[Candidate]) -> list[Candidate]:
        # The cross-encoder truncates long input, so a long chunk is scored in overlapping
        # windows (each with the section header) and keeps its best window's score. Otherwise
        # a clause near the end of a chunk, such as a punishment after the Illustrations,
        # would never be seen.
        size = self._settings.rerank_window_words
        overlap = self._settings.rerank_window_overlap_words
        passages: list[str] = []
        owners: list[int] = []
        for i, candidate in enumerate(pool):
            chunk = candidate.chunk
            for window in text_windows(chunk.text, size, overlap):
                passages.append(f"{chunk.context_header}\n{window}")
                owners.append(i)
        scores = await asyncio.to_thread(self._reranker.score, query, passages)
        best = [0.0] * len(pool)
        for owner, score in zip(owners, scores, strict=True):
            best[owner] = max(best[owner], score)
        for candidate, score in zip(pool, best, strict=True):
            candidate.rerank_score = score
        # Stable sort: equal scores keep their fused order.
        by_score = sorted(pool, key=lambda c: -(c.rerank_score or 0.0))
        if not self._settings.rerank_blend_with_search:
            return by_score
        # The cross-encoder favours short passages that restate the query, so a long section
        # that search ranked first (e.g. the general punishment for theft) can drop out of the
        # top k. Fusing both orders keeps the search signal; rerank_score is left untouched
        # for the relevance threshold.
        by_id = {c.chunk.id: c for c in pool}
        blended = reciprocal_rank_fusion(
            [[c.chunk.id for c in pool], [c.chunk.id for c in by_score]], k=self._settings.rrf_k
        )
        return [by_id[chunk_id] for chunk_id, _ in blended]
