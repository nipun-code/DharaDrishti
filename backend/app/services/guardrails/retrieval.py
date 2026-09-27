"""Retrieval guardrails (SPEC §8.2): refuse when nothing relevant was found (never guess)."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.generation.context import Source
from app.services.retrieval.types import RetrievalMode, RetrievalResult


@dataclass(frozen=True, slots=True)
class RelevanceDecision:
    refuse: bool
    reason: str | None = None
    best_score: float | None = None


def check_relevance(result: RetrievalResult, threshold: float) -> RelevanceDecision:
    """Refuse if there are no results, or (hybrid_rerank) the best re-rank score is below the
    threshold. Explicitly referenced sections (direct hits) always count as relevant."""
    if not result.final:
        return RelevanceDecision(refuse=True, reason="not_found")
    if result.direct:
        return RelevanceDecision(refuse=False)
    if result.mode != RetrievalMode.HYBRID_RERANK:
        return RelevanceDecision(refuse=False)  # other modes have no calibrated score
    scores = [c.rerank_score for c in result.final if c.rerank_score is not None]
    best = max(scores) if scores else 0.0
    if best < threshold:
        return RelevanceDecision(refuse=True, reason="low_relevance", best_score=best)
    return RelevanceDecision(refuse=False, best_score=best)


def repealed_acts(sources: Sequence[Source]) -> list[str]:
    return sorted({s.chunk.act_code for s in sources if s.repealed})
