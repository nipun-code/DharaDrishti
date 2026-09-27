"""Pure metric functions and the re-ranker refusal-threshold sweep."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

Key = tuple[str, str]  # (act code, section number)


def unique_in_order(keys: Sequence[Key]) -> list[Key]:
    """Sections in first-seen order: several chunks of one section count once."""
    return list(dict.fromkeys(keys))


def recall_at_k(retrieved: Sequence[Key], expected: set[Key], k: int) -> float:
    if not expected:
        raise ValueError("recall is undefined without expected sections")
    return len(set(unique_in_order(retrieved)[:k]) & expected) / len(expected)


def reciprocal_rank(retrieved: Sequence[Key], expected: set[Key]) -> float:
    for rank, key in enumerate(unique_in_order(retrieved), start=1):
        if key in expected:
            return 1.0 / rank
    return 0.0


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolated percentile (p in [0, 100]), like numpy's default."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


# ---------------------------------------------------------------- threshold sweep
@dataclass(frozen=True, slots=True)
class ThresholdSample:
    """One question: best re-rank score, and whether the system SHOULD answer it
    (in scope and a relevant section was retrieved) or refuse it."""

    best_score: float
    should_answer: bool


@dataclass(frozen=True, slots=True)
class ThresholdPoint:
    threshold: float
    balanced_accuracy: float
    answer_recall: float  # share of answerable questions that would be answered
    refusal_recall: float  # share of should-refuse questions that would be refused


def evaluate_threshold(samples: Sequence[ThresholdSample], threshold: float) -> ThresholdPoint:
    answerable = [s for s in samples if s.should_answer]
    refusable = [s for s in samples if not s.should_answer]
    answer_recall = mean([1.0 if s.best_score >= threshold else 0.0 for s in answerable])
    refusal_recall = mean([1.0 if s.best_score < threshold else 0.0 for s in refusable])
    parts = [r for r in (answer_recall, refusal_recall) if r is not None]
    return ThresholdPoint(
        threshold=round(threshold, 4),
        balanced_accuracy=round(sum(parts) / len(parts), 4) if parts else 0.0,
        answer_recall=round(answer_recall, 4) if answer_recall is not None else 0.0,
        refusal_recall=round(refusal_recall, 4) if refusal_recall is not None else 0.0,
    )


def sweep_thresholds(
    samples: Sequence[ThresholdSample], *, step: float = 0.01
) -> tuple[ThresholdPoint | None, list[ThresholdPoint]]:
    """Try thresholds 0..1; best = highest balanced accuracy, ties -> the lowest threshold
    (refuse as little as possible for the same accuracy). Returns (best, curve)."""
    if not samples:
        return None, []
    candidates = sorted({round(i * step, 4) for i in range(int(1 / step) + 1)})
    curve = [evaluate_threshold(samples, t) for t in candidates]
    best = max(curve, key=lambda p: (p.balanced_accuracy, -p.threshold))
    return best, curve
