"""Small structured LLM tasks with strict-JSON output and safe fallbacks:
query rewriting, topic classification and the faithfulness judge."""

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from app.services.generation.context import Source, format_sources
from app.services.generation.prompts import (
    FAITHFULNESS_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    TOPIC_SYSTEM_PROMPT,
)
from app.services.llm.base import ChatMessage, LLMError, LLMRequest, LLMResponse
from app.services.llm.fallback import LLMClient

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
MAX_REWRITES = 3
_MAX_QUERY_CHARS = 300


@dataclass(slots=True)
class UsageMeter:
    """Accumulates token usage (and the last provider/model) across a request's LLM calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider: str | None = None
    model: str | None = None
    calls: list[str] = field(default_factory=list)

    def add(self, response: LLMResponse, purpose: str) -> None:
        self.prompt_tokens += response.prompt_tokens
        self.completion_tokens += response.completion_tokens
        self.provider, self.model = response.provider, response.model
        self.calls.append(purpose)

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object, tolerating ```json fences and text around the object."""
    cleaned = _FENCE_RE.sub("", text.strip())
    candidates = [cleaned]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


async def _json_call(
    llm: LLMClient, meter: UsageMeter, *, purpose: str, system: str, user: str, max_tokens: int
) -> dict[str, Any] | None:
    request = LLMRequest(
        messages=(ChatMessage("system", system), ChatMessage("user", user)),
        max_tokens=max_tokens,
        temperature=0.0,
        json_mode=True,
        purpose=purpose,
    )
    try:
        response = await llm.complete(request)
    except LLMError as exc:
        logger.warning("llm_task_failed", extra={"purpose": purpose, "error": str(exc)})
        return None
    meter.add(response, purpose)
    parsed = parse_json_object(response.text)
    if parsed is None:
        logger.warning("llm_task_bad_json", extra={"purpose": purpose})
    return parsed


# ---------------------------------------------------------------- query rewriting
async def rewrite_query(llm: LLMClient, meter: UsageMeter, question: str) -> list[str] | None:
    """Up to 3 search queries in legal terminology, or None on any failure (use the original)."""
    data = await _json_call(
        llm, meter, purpose="rewrite", system=REWRITE_SYSTEM_PROMPT, user=question, max_tokens=200
    )
    queries = data.get("queries") if data else None
    if not isinstance(queries, list):
        return None
    cleaned = [
        " ".join(q.split())[:_MAX_QUERY_CHARS] for q in queries if isinstance(q, str) and q.strip()
    ]
    return cleaned[:MAX_REWRITES] or None


# ---------------------------------------------------------------- topic scope
TopicCategory = Literal["legal", "off_topic", "harmful", "unknown"]


async def classify_topic(llm: LLMClient, meter: UsageMeter, question: str) -> TopicCategory:
    """Returns "unknown" if the classifier fails; callers then allow the question."""
    data = await _json_call(
        llm,
        meter,
        purpose="topic",
        system=TOPIC_SYSTEM_PROMPT,
        user=f"<message>{question}</message>",
        max_tokens=60,
    )
    category = data.get("category") if data else None
    if category in {"legal", "off_topic", "harmful"}:
        return cast(TopicCategory, category)
    return "unknown"


# ---------------------------------------------------------------- faithfulness
@dataclass(frozen=True, slots=True)
class FaithfulnessVerdict:
    faithful: bool | None  # None = the judge failed; treated as unchecked
    unsupported_claims: tuple[str, ...] = ()


async def judge_faithfulness(
    llm: LLMClient, meter: UsageMeter, sources: Sequence[Source], answer: str
) -> FaithfulnessVerdict:
    user = f"SOURCES:\n{format_sources(sources)}\n\nANSWER:\n{answer}"
    data = await _json_call(
        llm,
        meter,
        purpose="faithfulness",
        system=FAITHFULNESS_SYSTEM_PROMPT,
        user=user,
        max_tokens=400,
    )
    if not data or not isinstance(data.get("faithful"), bool):
        return FaithfulnessVerdict(faithful=None)
    claims = data.get("unsupported_claims") or []
    return FaithfulnessVerdict(
        faithful=data["faithful"],
        unsupported_claims=tuple(str(c) for c in claims if isinstance(c, str | int | float))[:10],
    )
