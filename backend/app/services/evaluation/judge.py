"""LLM-as-judge for generation quality (strict JSON, scores in [0, 1])."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.generation.context import Source, format_sources
from app.services.generation.llm_tasks import UsageMeter, parse_json_object
from app.services.llm.base import ChatMessage, LLMError, LLMRequest
from app.services.llm.fallback import LLMClient

FAITHFULNESS_JUDGE_PROMPT = """You grade whether an ANSWER is supported by numbered SOURCES from Indian bare acts.

Score = fraction of the answer's factual claims that the sources directly support (1.0 = every claim supported, 0.0 = none). Paraphrase is fine; invented penalties, numbers, conditions or sections are not. [n] markers refer to source numbers.

Reply with strict JSON only: {"score": <number 0..1>, "unsupported_claims": ["..."]}"""

RELEVANCE_JUDGE_PROMPT = """You grade how well an ANSWER addresses a user's QUESTION about Indian law.

Score 1.0 = directly and completely answers the question; 0.5 = partially; 0.0 = does not address it. Judge relevance and completeness only, not style. If a REFERENCE answer is given, use it to judge completeness.

Reply with strict JSON only: {"score": <number 0..1>, "reason": "<a few words>"}"""


@dataclass(frozen=True, slots=True)
class JudgeScore:
    score: float | None  # None = the judge failed (excluded from averages)
    note: str | None = None


def _score(data: dict[str, object] | None) -> float | None:
    value = data.get("score") if data else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return min(1.0, max(0.0, float(value)))


async def _judge(
    llm: LLMClient, meter: UsageMeter, purpose: str, system: str, user: str
) -> dict[str, object] | None:
    request = LLMRequest(
        messages=(ChatMessage("system", system), ChatMessage("user", user)),
        max_tokens=400,
        temperature=0.0,
        json_mode=True,
        purpose=purpose,
    )
    try:
        response = await llm.complete(request)
    except LLMError:
        return None
    meter.add(response, purpose)
    return parse_json_object(response.text)


async def judge_faithfulness(
    llm: LLMClient, meter: UsageMeter, sources: Sequence[Source], answer: str
) -> JudgeScore:
    data = await _judge(
        llm,
        meter,
        "eval_faithfulness",
        FAITHFULNESS_JUDGE_PROMPT,
        f"SOURCES:\n{format_sources(sources)}\n\nANSWER:\n{answer}",
    )
    claims = data.get("unsupported_claims") if data else None
    note = "; ".join(str(c) for c in claims[:5]) if isinstance(claims, list) and claims else None
    return JudgeScore(_score(data), note)


async def judge_relevance(
    llm: LLMClient, meter: UsageMeter, question: str, answer: str, reference: str | None
) -> JudgeScore:
    user = f"QUESTION:\n{question}\n\nANSWER:\n{answer}"
    if reference:
        user += f"\n\nREFERENCE ANSWER:\n{reference}"
    data = await _judge(llm, meter, "eval_relevance", RELEVANCE_JUDGE_PROMPT, user)
    reason = data.get("reason") if data else None
    return JudgeScore(_score(data), str(reason) if reason else None)
