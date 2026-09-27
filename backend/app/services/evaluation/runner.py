"""Evaluation runner (SPEC §10): compares retrieval modes on the golden dataset.

For every mode and question:
  * retrieval  -> recall@5, recall@10, MRR (match on act + section), retrieval latency
  * generation -> the real query pipeline (cache and query logging off), then LLM judges for
                  faithfulness (against the same numbered sources) and answer relevance;
                  out-of-scope questions score on whether they were refused
Plus a sweep of the re-ranker refusal threshold using the hybrid_rerank results.

CLI (runs in-process and saves an eval_runs row):
    python -m app.services.evaluation.runner --modes all --limit 20 [--no-generation]
"""

import argparse
import asyncio
import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.evaluation.dataset import GoldenItem, category_counts
from app.services.evaluation.judge import judge_faithfulness, judge_relevance
from app.services.evaluation.metrics import (
    Key,
    ThresholdSample,
    mean,
    percentile,
    ratio,
    recall_at_k,
    reciprocal_rank,
    sweep_thresholds,
    unique_in_order,
)
from app.services.generation.context import build_sources
from app.services.generation.llm_tasks import UsageMeter
from app.services.llm.fallback import LLMClient
from app.services.query.pipeline import QueryPipeline, ResultEvent, Retriever
from app.services.query.store import QueryLogEntry, QueryStore
from app.services.retrieval.types import RetrievalMode, RetrievalResult

logger = logging.getLogger(__name__)

ALL_MODES = tuple(RetrievalMode)
EVAL_USER_ID = uuid.UUID(int=0)  # budget/log placeholder; both are no-ops during evaluation
_ANSWER_CHARS = 2000
_CURVE_STEP = 0.05

Progress = Callable[[int], Awaitable[None]]


class EvalConfig(BaseModel):
    modes: list[RetrievalMode] = Field(default_factory=lambda: list(ALL_MODES), min_length=1)
    limit: int | None = Field(default=None, ge=1)
    generation: bool = True
    use_cache: bool = False


@dataclass(slots=True)
class EvalReport:
    metrics: dict[str, Any]
    per_question: list[dict[str, Any]]


# ---------------------------------------------------------------- pipeline plumbing
class _CapturingRetriever:
    """Wraps the real retriever and remembers the last result (the sources the answer saw)."""

    def __init__(self, inner: Retriever) -> None:
        self._inner = inner
        self.last: RetrievalResult | None = None

    async def retrieve(self, query: str, **kwargs: Any) -> RetrievalResult:
        self.last = await self._inner.retrieve(query, **kwargs)
        return self.last


class _EvalStore:
    """Doesn't write query_logs (evaluation must not pollute analytics); keeps the entry."""

    def __init__(self, inner: QueryStore | None) -> None:
        self._inner = inner
        self.last: QueryLogEntry | None = None

    async def log(self, entry: QueryLogEntry) -> uuid.UUID:
        self.last = entry
        return uuid.uuid4()

    async def mapped_sections(self, numbers: Iterable[str]) -> set[str]:
        return await self._inner.mapped_sections(numbers) if self._inner else set()


class _NullCache:
    async def get(self, key: str) -> dict[str, Any] | None:
        return None

    async def set(self, key: str, payload: dict[str, Any]) -> None:
        return None


class _NullBudget:
    async def add(self, user_id: uuid.UUID, tokens: int) -> None:
        return None


# ---------------------------------------------------------------- runner
@dataclass(slots=True)
class _ModeRows:
    rows: list[dict[str, Any]] = field(default_factory=list)


class EvaluationRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        retriever: Retriever,
        llm: LLMClient,
        store: QueryStore | None = None,
        cache: Any = None,
    ) -> None:
        self._settings = settings
        self._retriever = retriever
        self._llm = llm
        self._store = store
        self._cache = cache

    async def run(
        self, items: Sequence[GoldenItem], config: EvalConfig, progress: Progress | None = None
    ) -> EvalReport:
        items = list(items)[: config.limit] if config.limit else list(items)
        total = len(items) * len(config.modes)
        done = 0
        per_mode: dict[str, _ModeRows] = {}
        for mode in config.modes:
            bucket = per_mode.setdefault(mode.value, _ModeRows())
            for item in items:
                bucket.rows.append(await self._evaluate(item, mode, config))
                done += 1
                if progress:
                    await progress(int(done * 100 / total))
        metrics: dict[str, Any] = {
            "dataset": {"questions": len(items), "by_category": category_counts(items)},
            "generation": config.generation,
            "modes": {mode: _aggregate(b.rows, config) for mode, b in per_mode.items()},
            "threshold": self._threshold_report(per_mode.get(RetrievalMode.HYBRID_RERANK.value)),
        }
        return EvalReport(metrics, [row for b in per_mode.values() for row in b.rows])

    async def _evaluate(
        self, item: GoldenItem, mode: RetrievalMode, config: EvalConfig
    ) -> dict[str, Any]:
        row: dict[str, Any] = {"id": item.id, "category": item.category, "mode": mode.value}
        try:
            await self._evaluate_retrieval(item, mode, row)
            if config.generation:
                await self._evaluate_generation(item, mode, config, row)
        except Exception as exc:  # one bad question must not sink the run
            logger.exception(
                "eval_question_failed", extra={"question_id": item.id, "mode": mode.value}
            )
            row["error"] = (
                exc.message if isinstance(exc, AppError) else f"{type(exc).__name__}: {exc}"
            )
        return row

    async def _evaluate_retrieval(
        self, item: GoldenItem, mode: RetrievalMode, row: dict[str, Any]
    ) -> None:
        started = time.perf_counter()
        result = await self._retriever.retrieve(
            item.question, mode=mode, top_k=self._settings.eval_retrieval_k
        )
        row["retrieval_ms"] = round((time.perf_counter() - started) * 1000, 1)
        keys: list[Key] = [(c.chunk.act_code, c.chunk.section_number) for c in result.final]
        row["retrieved"] = [f"{act} {section}" for act, section in unique_in_order(keys)][:10]
        row["has_direct"] = bool(result.direct)
        scores = [c.rerank_score for c in result.final if c.rerank_score is not None]
        row["best_rerank_score"] = round(max(scores), 4) if scores else None
        if item.category != "out_of_scope":
            expected = item.expected_keys
            row["recall_at_5"] = recall_at_k(keys, expected, 5)
            row["recall_at_10"] = recall_at_k(keys, expected, 10)
            row["reciprocal_rank"] = reciprocal_rank(keys, expected)

    async def _evaluate_generation(
        self, item: GoldenItem, mode: RetrievalMode, config: EvalConfig, row: dict[str, Any]
    ) -> None:
        capturing = _CapturingRetriever(self._retriever)
        store = _EvalStore(self._store)
        pipeline = QueryPipeline(
            settings=self._settings,
            llm=self._llm,
            retriever=capturing,
            cache=self._cache if (config.use_cache and self._cache is not None) else _NullCache(),
            budget=_NullBudget(),
            store=store,
        )
        response = None
        async for event in pipeline.run(item.question, user_id=EVAL_USER_ID, mode=mode):
            if isinstance(event, ResultEvent):
                response = event.response
        if response is None:  # pragma: no cover - the pipeline always yields a result
            raise RuntimeError("pipeline returned no result")

        row.update(
            answer=response.answer[:_ANSWER_CHARS],
            refused=response.refused,
            refusal_reason=response.refusal_reason,
            answer_ms=response.latency_ms,
            cache_hit=response.cache_hit,
            tokens=(store.last.prompt_tokens or 0) + (store.last.completion_tokens or 0)
            if store.last
            else None,
        )
        if item.category == "out_of_scope" or response.refused or capturing.last is None:
            return
        meter = UsageMeter()
        sources, _ = build_sources(capturing.last.final, self._settings.context_max_tokens)
        faithfulness = await judge_faithfulness(self._llm, meter, sources, response.answer)
        relevance = await judge_relevance(
            self._llm, meter, item.question, response.answer, item.reference_answer
        )
        row.update(
            faithfulness=faithfulness.score,
            faithfulness_note=faithfulness.note,
            relevance=relevance.score,
            relevance_note=relevance.note,
        )

    def _threshold_report(self, bucket: _ModeRows | None) -> dict[str, Any] | None:
        """Pick the re-rank threshold that best separates answerable from should-refuse
        questions. Questions with explicit section references are excluded (they bypass it)."""
        if bucket is None:
            return None
        samples = [
            ThresholdSample(
                best_score=row["best_rerank_score"] or 0.0,
                should_answer=row["category"] != "out_of_scope" and row.get("recall_at_10", 0) > 0,
            )
            for row in bucket.rows
            if "error" not in row and not row.get("has_direct")
        ]
        best, curve = sweep_thresholds(samples)
        current = self._settings.rerank_refusal_threshold
        answerable = sum(s.should_answer for s in samples)
        report: dict[str, Any] = {
            "current": current,
            "samples": len(samples),
            "answerable": answerable,
            "should_refuse": len(samples) - answerable,
            "recommended": None,
            "curve": [
                {
                    "threshold": p.threshold,
                    "balanced_accuracy": p.balanced_accuracy,
                    "answer_recall": p.answer_recall,
                    "refusal_recall": p.refusal_recall,
                }
                for p in curve
                if round(p.threshold / _CURVE_STEP, 6).is_integer()
            ],
        }
        if best is not None:
            report.update(
                recommended=best.threshold,
                balanced_accuracy=best.balanced_accuracy,
                answer_recall=best.answer_recall,
                refusal_recall=best.refusal_recall,
            )
            if not answerable or answerable == len(samples):
                report["note"] = (
                    "Needs both answerable and should-refuse questions (add out_of_scope rows) "
                    "for a meaningful threshold."
                )
        return report


def _values(rows: Sequence[dict[str, Any]], key: str) -> list[float]:
    return [float(r[key]) for r in rows if r.get(key) is not None]


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


def _aggregate(rows: Sequence[dict[str, Any]], config: EvalConfig) -> dict[str, Any]:
    ok = [r for r in rows if "error" not in r]
    in_scope = [r for r in ok if r["category"] != "out_of_scope"]
    retrieval_ms = _values(ok, "retrieval_ms")
    result: dict[str, Any] = {
        "questions": len(rows),
        "errors": len(rows) - len(ok),
        "recall_at_5": _round(mean(_values(in_scope, "recall_at_5"))),
        "recall_at_10": _round(mean(_values(in_scope, "recall_at_10"))),
        "mrr": _round(mean(_values(in_scope, "reciprocal_rank"))),
        "retrieval_latency_p50_ms": _round(percentile(retrieval_ms, 50), 1),
        "retrieval_latency_p95_ms": _round(percentile(retrieval_ms, 95), 1),
    }
    if not config.generation:
        return result
    answered = [r for r in ok if "refused" in r]
    out_of_scope = [r for r in answered if r["category"] == "out_of_scope"]
    in_scope_answered = [r for r in answered if r["category"] != "out_of_scope"]
    answer_ms = _values(answered, "answer_ms")
    result.update(
        faithfulness=_round(mean(_values(answered, "faithfulness"))),
        answer_relevance=_round(mean(_values(answered, "relevance"))),
        judged=len(_values(answered, "faithfulness")),
        out_of_scope_refusal_accuracy=_round(
            ratio(sum(r["refused"] for r in out_of_scope), len(out_of_scope))
        ),
        false_refusal_rate=_round(
            ratio(sum(r["refused"] for r in in_scope_answered), len(in_scope_answered))
        ),
        answer_latency_p50_ms=_round(percentile(answer_ms, 50), 1),
        answer_latency_p95_ms=_round(percentile(answer_ms, 95), 1),
        avg_tokens=_round(mean(_values(answered, "tokens")), 1),
        cache_hit_rate=_round(ratio(sum(bool(r.get("cache_hit")) for r in answered), len(answered)))
        if config.use_cache
        else None,
    )
    return result


# ---------------------------------------------------------------- CLI
def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.evaluation.runner", description="Run the evaluation."
    )
    parser.add_argument(
        "--modes", default="all", help='"all" or comma-separated, e.g. hybrid,vector'
    )
    parser.add_argument("--limit", type=int, help="Only the first N questions.")
    parser.add_argument(
        "--no-generation", action="store_true", help="Retrieval metrics only (no LLM)."
    )
    parser.add_argument(
        "--use-cache", action="store_true", help="Allow cached answers (off by default)."
    )
    return parser.parse_args(argv)


def _modes(value: str) -> list[RetrievalMode]:
    if value.strip().lower() == "all":
        return list(ALL_MODES)
    try:
        return [RetrievalMode(m.strip().lower()) for m in value.split(",") if m.strip()]
    except ValueError as exc:
        raise SystemExit(f"Unknown mode in {value!r}. Use: all, {', '.join(ALL_MODES)}") from exc


def _cell(value: float | None, key: str) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}" if key.endswith("_ms") else f"{value:.3f}"


def _print_report(metrics: dict[str, Any]) -> None:
    columns = [
        ("recall_at_5", "R@5"),
        ("recall_at_10", "R@10"),
        ("mrr", "MRR"),
        ("faithfulness", "Faith"),
        ("answer_relevance", "Relev"),
        ("out_of_scope_refusal_accuracy", "OOS-ref"),
        ("retrieval_latency_p50_ms", "ret p50 ms"),
        ("answer_latency_p95_ms", "ans p95 ms"),
    ]
    out = sys.stdout
    out.write(f"\n{'mode':<15}" + "".join(f"{label:>12}" for _, label in columns) + "\n")
    for mode, values in metrics["modes"].items():
        cells = "".join(f"{_cell(values.get(key), key):>12}" for key, _ in columns)
        out.write(f"{mode:<15}{cells}\n")
    threshold = metrics.get("threshold")
    if threshold and threshold.get("recommended") is not None:
        out.write(
            f"\nRe-ranker refusal threshold: recommended {threshold['recommended']} "
            f"(balanced accuracy {threshold['balanced_accuracy']}, "
            f"current {threshold['current']}, {threshold['samples']} questions)\n"
        )
        if threshold.get("note"):
            out.write(f"Note: {threshold['note']}\n")


def main(argv: Sequence[str] | None = None) -> int:
    from app.core.config import get_settings  # noqa: PLC0415
    from app.core.logging import configure_logging  # noqa: PLC0415
    from app.services.evaluation.service import run_evaluation_cli  # noqa: PLC0415

    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    config = EvalConfig(
        modes=_modes(args.modes),
        limit=args.limit,
        generation=not args.no_generation,
        use_cache=args.use_cache,
    )
    try:
        run_id, metrics = asyncio.run(run_evaluation_cli(settings, config))
    except AppError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    _print_report(metrics)
    sys.stdout.write(f"\nSaved as eval run {run_id}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
