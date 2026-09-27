"""Evaluation: metric maths, dataset validation, and the runner end to end with a scripted LLM.
Questions and sections are placeholders."""

import json
from typing import Any

import pytest

from app.core.config import Settings
from app.db.models.enums import ActStatus
from app.services.evaluation.dataset import DatasetError, GoldenItem, parse_golden
from app.services.evaluation.metrics import (
    ThresholdSample,
    percentile,
    recall_at_k,
    reciprocal_rank,
    sweep_thresholds,
)
from app.services.evaluation.runner import EvalConfig, EvaluationRunner
from app.services.retrieval.types import (
    Candidate,
    CandidateSource,
    ChunkRecord,
    RetrievalMode,
    RetrievalResult,
)
from tests.conftest import FakeLLM, MemoryQueryStore


# ---------------------------------------------------------------- metrics
def test_recall_and_mrr_count_sections_not_chunks() -> None:
    # Two chunks of BNS 1 must not push BNS 2 out of the top 2.
    retrieved = [("BNS", "1"), ("BNS", "1"), ("BNS", "2"), ("IPC", "9")]
    expected = {("BNS", "2"), ("IPC", "9")}

    assert recall_at_k(retrieved, expected, 2) == 0.5
    assert recall_at_k(retrieved, expected, 5) == 1.0
    assert reciprocal_rank(retrieved, expected) == 0.5
    assert reciprocal_rank(retrieved, {("ITA", "1")}) == 0.0


def test_percentile_interpolates() -> None:
    assert percentile([10, 20, 30, 40], 50) == 25
    assert percentile([10, 20, 30, 40], 95) == pytest.approx(38.5)
    assert percentile([], 50) is None


def test_threshold_sweep_separates_and_prefers_lowest_tie() -> None:
    samples = [
        ThresholdSample(0.9, True),
        ThresholdSample(0.6, True),
        ThresholdSample(0.3, False),
        ThresholdSample(0.1, False),
    ]

    best, curve = sweep_thresholds(samples)

    assert best is not None
    assert best.balanced_accuracy == 1.0
    assert best.threshold == 0.31  # lowest value that still refuses 0.3 and answers 0.6
    assert len(curve) == 101


# ---------------------------------------------------------------- dataset
def row(**overrides: Any) -> str:
    base = {
        "id": "q1",
        "question": "What does placeholder section say?",
        "expected_sections": [{"act": "bns", "section": "318(4)"}],
        "category": "exact_ref",
    }
    return json.dumps({**base, **overrides})


def test_parse_normalizes_and_skips_blank_and_comment_lines() -> None:
    items = parse_golden(
        "\n".join(
            [row(), "", "// comment", row(id="q2", category="out_of_scope", expected_sections=[])]
        )
    )

    assert [i.id for i in items] == ["q1", "q2"]
    assert items[0].expected_keys == {("BNS", "318")}


def test_parse_reports_every_problem_with_line_numbers() -> None:
    text = "\n".join(
        [
            row(),
            "{not json",
            row(id="q3", category="out_of_scope"),  # oos with sections
            row(id="q4", expected_sections=[]),  # in-scope without sections
            row(id="q5", category="nonsense"),
            row(id="q6", expected_sections=[{"act": "BNS", "section": "abc"}]),
            row(),  # duplicate id q1
        ]
    )

    with pytest.raises(DatasetError) as info:
        parse_golden(text)

    errors = info.value.errors
    assert [e.split(":")[0] for e in errors] == [f"line {n}" for n in (2, 3, 4, 5, 6, 7)]
    assert "duplicate id 'q1'" in errors[-1]


# ---------------------------------------------------------------- runner
def chunk(chunk_id: int, act: str, section: str, rerank: float) -> Candidate:
    record = ChunkRecord(
        id=chunk_id,
        act_code=act,
        act_status=ActStatus.IN_FORCE,
        chapter_number=None,
        chapter_title=None,
        section_number=section,
        section_title=f"Placeholder {section}",
        subsection=None,
        text=f"Placeholder text of section {section}.",
        page_start=1,
        page_end=1,
    )
    return Candidate(chunk=record, source=CandidateSource.SEARCH, rerank_score=rerank)


class ScriptedRetriever:
    """Returns fixed results per question; raises for the question marked 'boom'."""

    def __init__(self) -> None:
        self.results = {
            "Q-hit": [chunk(1, "BNS", "1", 0.9), chunk(2, "BNS", "2", 0.4)],
            "Q-second": [chunk(3, "BNS", "7", 0.8), chunk(4, "BNS", "3", 0.7)],
            "Q-oos": [chunk(5, "BNS", "9", 0.05)],
        }

    async def retrieve(self, query: str, **kwargs: Any) -> RetrievalResult:
        if query == "Q-boom":
            raise RuntimeError("index offline")
        final = self.results[query]
        return RetrievalResult(
            query=query,
            mode=kwargs.get("mode", RetrievalMode.HYBRID_RERANK),
            search_queries=[query],
            act_filter=None,
            section_refs=[],
            direct=[],
            final=final,
        )


GOLDEN = [
    GoldenItem.model_validate(
        {
            "id": "hit",
            "question": "Q-hit",
            "expected_sections": [{"act": "BNS", "section": "1"}],
            "category": "semantic",
        }
    ),
    GoldenItem.model_validate(
        {
            "id": "second",
            "question": "Q-second",
            "expected_sections": [{"act": "BNS", "section": "3"}],
            "category": "semantic",
        }
    ),
    GoldenItem.model_validate({"id": "oos", "question": "Q-oos", "category": "out_of_scope"}),
    GoldenItem.model_validate(
        {
            "id": "boom",
            "question": "Q-boom",
            "expected_sections": [{"act": "BNS", "section": "1"}],
            "category": "semantic",
        }
    ),
]


@pytest.fixture
def eval_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"topic_classifier_enabled": False, "query_rewrite_enabled": False}
    )


async def test_runner_retrieval_only_metrics_and_threshold(eval_settings: Settings) -> None:
    runner = EvaluationRunner(settings=eval_settings, retriever=ScriptedRetriever(), llm=FakeLLM())
    progress: list[int] = []

    async def on_progress(p: int) -> None:
        progress.append(p)

    report = await runner.run(
        GOLDEN,
        EvalConfig(modes=[RetrievalMode.HYBRID_RERANK, RetrievalMode.KEYWORD], generation=False),
        on_progress,
    )

    metrics = report.metrics["modes"]["hybrid_rerank"]
    assert metrics["recall_at_5"] == 1.0  # both answerable questions hit within 5
    assert metrics["mrr"] == 0.75  # ranks 1 and 2
    assert metrics["errors"] == 1  # Q-boom failed but did not stop the run
    assert "faithfulness" not in metrics
    assert progress[-1] == 100
    assert len(report.per_question) == 8
    failed = next(r for r in report.per_question if r["id"] == "boom")
    assert "index offline" in failed["error"]
    threshold = report.metrics["threshold"]
    assert threshold["samples"] == 3
    assert 0.05 < threshold["recommended"] <= 0.8  # answers 0.9 & 0.8, refuses the 0.05 OOS
    assert threshold["balanced_accuracy"] == 1.0
    assert report.metrics["dataset"]["by_category"]["out_of_scope"] == 1


async def test_runner_generation_judges_answers_and_scores_refusals(
    eval_settings: Settings,
) -> None:
    llm = FakeLLM(
        answer="The placeholder rule applies [1].",
        eval_faithfulness='{"score": 0.8, "unsupported_claims": ["x"]}',
        eval_relevance='{"score": 1, "reason": "direct"}',
    )
    runner = EvaluationRunner(
        settings=eval_settings.model_copy(update={"rerank_refusal_threshold": 0.2}),
        retriever=ScriptedRetriever(),
        llm=llm,
        store=MemoryQueryStore(),
    )

    report = await runner.run(GOLDEN[:3], EvalConfig(modes=[RetrievalMode.HYBRID_RERANK]))

    metrics = report.metrics["modes"]["hybrid_rerank"]
    assert metrics["faithfulness"] == 0.8
    assert metrics["answer_relevance"] == 1.0
    assert metrics["judged"] == 2
    assert metrics["out_of_scope_refusal_accuracy"] == 1.0  # 0.05 < threshold -> refused
    assert metrics["false_refusal_rate"] == 0.0
    assert (metrics["avg_tokens"] or 0) > 0
    assert metrics["cache_hit_rate"] is None  # cache is off during evaluation
    oos = next(r for r in report.per_question if r["id"] == "oos")
    assert oos["refused"] is True
    assert "faithfulness" not in oos
    assert llm.purposes.count("eval_faithfulness") == 2
