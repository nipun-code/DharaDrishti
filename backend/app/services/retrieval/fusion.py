"""Reciprocal Rank Fusion (Cormack, Clarke & Buettcher, 2009).

    score(d) = sum over rankings r containing d of  1 / (k + rank_r(d)),  rank starting at 1

Only ranks matter, so keyword scores (ts_rank_cd) and vector scores (cosine) — which live on
different scales — can be combined without normalisation. A larger `k` flattens the curve,
giving lower-ranked items relatively more weight.
"""

from collections.abc import Hashable, Sequence
from typing import TypeVar

KeyT = TypeVar("KeyT", bound=Hashable)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[KeyT]], k: int = 60
) -> list[tuple[KeyT, float]]:
    """Fuse ranked lists of ids into one list of (id, score), best first.

    Duplicates within one ranking count only at their best (first) position. Ties are broken
    by the best single rank an item achieved, then by first appearance, so the output is
    deterministic.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    scores: dict[KeyT, float] = {}
    best_rank: dict[KeyT, int] = {}
    first_seen: dict[KeyT, int] = {}
    order = 0
    for ranking in rankings:
        seen_here: set[KeyT] = set()
        for rank, key in enumerate(ranking, start=1):
            if key in seen_here:
                continue
            seen_here.add(key)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            best_rank[key] = min(best_rank.get(key, rank), rank)
            if key not in first_seen:
                first_seen[key] = order
                order += 1
    return sorted(
        scores.items(), key=lambda item: (-item[1], best_rank[item[0]], first_seen[item[0]])
    )
