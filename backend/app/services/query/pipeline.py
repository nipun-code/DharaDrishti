"""The query pipeline (SPEC §7) with every guardrail from SPEC §8.

One async generator drives both endpoints: POST /query consumes it to completion and returns
the final result; POST /query/stream forwards each event over SSE. Order of steps:

    input guardrails (sanitise, injection, harmful intent, PII redaction)
    -> exact-match cache
    -> topic-scope classifier (LLM; skipped on cache hits, which were already classified)
    -> query rewriting (LLM, strict JSON; falls back to the original query)
    -> hybrid retrieval  -> relevance threshold (refuse without calling the LLM)
    -> context budget + repealed-act labels -> streamed grounded generation
    -> citation verifier -> faithfulness judge (+1 stricter regeneration) -> section verifier
    -> disclaimer, query log, cache write, token accounting
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.schemas.query import Citation, QueryResponse
from app.services.cache.exact import AnswerCache, cache_key
from app.services.generation.context import Source, answer_messages, build_sources
from app.services.generation.llm_tasks import (
    UsageMeter,
    classify_topic,
    judge_faithfulness,
    rewrite_query,
)
from app.services.generation.prompts import ANSWER_SYSTEM_PROMPT, STRICT_RETRY_INSTRUCTION
from app.services.guardrails.input import (
    detect_harmful_intent,
    detect_prompt_injection,
    redact_pii,
    sanitize_query,
)
from app.services.guardrails.output import mentioned_sections, verify_citations
from app.services.guardrails.retrieval import check_relevance, repealed_acts
from app.services.limits import TokenBudget
from app.services.llm.base import LLMError, LLMRequest
from app.services.llm.fallback import LLMClient
from app.services.query.store import QueryLogEntry, QueryStore
from app.services.retrieval.types import RetrievalMode, RetrievalResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- user-facing messages
REFUSALS = {
    "prompt_injection": (
        "I can only answer questions about Indian law. Please ask your question without "
        "instructions about how I should behave."
    ),
    "harmful_intent": (
        "I can't help with committing or concealing an offence or evading the law. I can explain "
        "what the law says about an offence, including its punishment."
    ),
    "off_topic": (
        "I can only answer questions about Indian statutes such as the BNS, BNSS, BSA, IPC and "
        "the IT Act. Please ask a question about the law."
    ),
    "not_found": (
        "I couldn't find this in the indexed acts, so I won't guess. Try rephrasing, naming the "
        "act or section, or check that the relevant act has been uploaded."
    ),
    "low_relevance": (
        "I couldn't find provisions in the indexed acts that clearly answer this, so I won't "
        "guess. Try rephrasing or naming the act or section."
    ),
    "no_valid_citations": (
        "I couldn't produce an answer that is supported by the indexed acts. Please try "
        "rephrasing your question or naming the act or section."
    ),
}
WARNING_UNFAITHFUL = (
    "Parts of this answer may not be fully supported by the cited sources. "
    "Please verify against the section text."
)
_SNIPPET_CHARS = 300


# ---------------------------------------------------------------- events
@dataclass(frozen=True, slots=True)
class StatusEvent:
    stage: str  # checking | searching | generating | verifying
    message: str


@dataclass(frozen=True, slots=True)
class TokenEvent:
    text: str


@dataclass(frozen=True, slots=True)
class ResultEvent:
    response: QueryResponse


QueryEvent = StatusEvent | TokenEvent | ResultEvent


class Retriever(Protocol):
    async def retrieve(
        self,
        query: str,
        *,
        acts: Sequence[str] | None = None,
        mode: RetrievalMode = RetrievalMode.HYBRID_RERANK,
        top_k: int | None = None,
        extra_queries: Sequence[str] = (),
    ) -> RetrievalResult: ...


@dataclass(slots=True)
class _Run:
    user_id: uuid.UUID
    query: str  # sanitised + PII-redacted
    acts: list[str] | None
    mode: RetrievalMode
    top_k: int
    started: float = field(default_factory=time.perf_counter)
    usage: UsageMeter = field(default_factory=UsageMeter)
    flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rewritten: list[str] = field(default_factory=list)
    chunk_ids: list[int] = field(default_factory=list)

    def flag(self, name: str) -> None:
        if name not in self.flags:
            self.flags.append(name)

    @property
    def latency_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


class QueryPipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        retriever: Retriever,
        cache: AnswerCache,
        budget: TokenBudget,
        store: QueryStore,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._retriever = retriever
        self._cache = cache
        self._budget = budget
        self._store = store

    def validate(self, raw_query: str) -> str:
        """Length/character guardrail. Call before streaming so errors are proper HTTP 422s."""
        return sanitize_query(
            raw_query,
            min_chars=self._settings.query_min_chars,
            max_chars=self._settings.query_max_chars,
        )

    async def run(
        self,
        raw_query: str,
        *,
        user_id: uuid.UUID,
        acts: Sequence[str] | None = None,
        mode: RetrievalMode = RetrievalMode.HYBRID_RERANK,
        top_k: int | None = None,
    ) -> AsyncIterator[QueryEvent]:
        query = self.validate(raw_query)
        redaction = redact_pii(query)
        run = _Run(
            user_id=user_id,
            query=redaction.text,
            acts=sorted({a.upper() for a in acts}) if acts else None,
            mode=mode,
            top_k=top_k or self._settings.retrieval_top_k,
        )
        if redaction.redacted:
            run.flag("pii_redacted")
        try:
            async for event in self._run(run):
                yield event
        finally:
            await self._budget.add(user_id, run.usage.total)

    async def _run(self, run: _Run) -> AsyncIterator[QueryEvent]:
        yield StatusEvent("checking", "Checking your question…")
        refusal = self._input_refusal(run)
        if refusal:
            yield await self._refuse(run, refusal)
            return

        key = cache_key(run.query, run.acts, run.mode.value, run.top_k)
        cached = await self._cache.get(key)
        if cached is not None:
            response = await self._from_cache(run, cached)
            yield TokenEvent(response.answer)
            yield ResultEvent(response)
            return

        refusal = await self._scope_and_rewrite(run)
        if refusal:
            yield await self._refuse(run, refusal)
            return

        yield StatusEvent("searching", "Searching the acts…")
        sources, refusal = await self._retrieve(run)
        if refusal:
            yield await self._refuse(run, refusal)
            return

        yield StatusEvent("generating", "Writing the answer…")
        draft = ""
        async for item in self._generate(run, sources):
            if isinstance(item, TokenEvent):
                yield item
            else:
                draft = item

        yield StatusEvent("verifying", "Checking citations…")
        answer, cited = await self._verify(run, sources, draft)
        if not cited:
            yield await self._refuse(run, "no_valid_citations")
            return
        yield await self._answer(run, key, sources, answer, cited)

    # ---------------------------------------------------------------- stages
    def _input_refusal(self, run: _Run) -> str | None:
        """Guardrails that need no LLM: prompt injection and harmful intent."""
        threshold = self._settings.injection_block_score
        if detect_prompt_injection(run.query, block_score=threshold).blocked:
            return "prompt_injection"
        if detect_harmful_intent(run.query):
            return "harmful_intent"
        return None

    async def _scope_and_rewrite(self, run: _Run) -> str | None:
        """LLM topic classifier (failure = allow), then query rewriting (failure = original)."""
        if self._settings.topic_classifier_enabled:
            category = await classify_topic(self._llm, run.usage, run.query)
            if category == "off_topic":
                return "off_topic"
            if category == "harmful":
                return "harmful_intent"
            if category == "unknown":
                run.flag("topic_unchecked")
        if self._settings.query_rewrite_enabled:
            rewrites = await rewrite_query(self._llm, run.usage, run.query)
            if rewrites is None:
                run.flag("rewrite_failed")
            else:
                run.rewritten = rewrites
        return None

    async def _retrieve(self, run: _Run) -> tuple[list[Source], str | None]:
        """Hybrid retrieval, relevance threshold (refuse without the LLM), context budget."""
        result = await self._retriever.retrieve(
            run.query, acts=run.acts, mode=run.mode, top_k=run.top_k, extra_queries=run.rewritten
        )
        run.chunk_ids = [c.chunk.id for c in result.final]
        decision = check_relevance(result, self._settings.rerank_refusal_threshold)
        if decision.refuse:
            return [], decision.reason or "not_found"
        sources, dropped = build_sources(result.final, self._settings.context_max_tokens)
        if dropped:
            run.flag("context_trimmed")
        return sources, None

    async def _generate(self, run: _Run, sources: list[Source]) -> AsyncIterator[TokenEvent | str]:
        """Stream the grounded answer: yields TokenEvents, then the full draft text (a str)."""
        draft = ""
        try:
            async for item in self._llm.stream(self._answer_request(run.query, sources)):
                if isinstance(item, str):
                    draft += item
                    yield TokenEvent(item)
                else:
                    run.usage.add(item, "answer")
                    draft = item.text
        except LLMError as exc:
            logger.exception("answer_generation_failed")
            run.flag("llm_unavailable")
            await self._log(run, answer=None, refused=True, reason="llm_unavailable")
            raise ServiceUnavailableError(
                "The answer service is temporarily unavailable. Please try again shortly."
            ) from exc
        yield draft

    async def _answer(
        self, run: _Run, key: str, sources: list[Source], answer: str, cited: set[int]
    ) -> ResultEvent:
        repealed = repealed_acts([s for s in sources if s.n in cited])
        if repealed:
            run.warnings.append(
                f"This answer cites a repealed act ({', '.join(repealed)}). Check the provision "
                "that replaced it before relying on it."
            )
        response = QueryResponse(
            answer=answer,
            citations=[_citation(s) for s in sources if s.n in cited],
            refused=False,
            warnings=run.warnings,
            latency_ms=run.latency_ms,
        )
        response.query_log_id = await self._log(run, answer=answer, refused=False)
        await self._cache.set(
            key,
            response.model_dump(include={"answer", "citations", "warnings"}, mode="json"),
        )
        return ResultEvent(response)

    # ---------------------------------------------------------------- verification
    async def _verify(self, run: _Run, sources: list[Source], draft: str) -> tuple[str, set[int]]:
        check = verify_citations(draft, len(sources))
        if check.invalid:
            run.flag("invalid_citation")
        if not check.cited:
            return check.text, set()
        answer, cited = check.text, set(check.cited)

        if self._settings.faithfulness_check_enabled:
            verdict = await judge_faithfulness(self._llm, run.usage, sources, answer)
            if verdict.faithful is None:
                run.flag("faithfulness_unchecked")
            elif not verdict.faithful:
                run.flag("unfaithful_regenerated")
                regenerated = await self._regenerate(run, sources, verdict.unsupported_claims)
                recheck = verify_citations(regenerated, len(sources)) if regenerated else None
                if recheck and recheck.cited:
                    answer, cited = recheck.text, set(recheck.cited)
                    second = await judge_faithfulness(self._llm, run.usage, sources, answer)
                    if second.faithful is False:
                        run.flag("unfaithful")
                        run.warnings.append(WARNING_UNFAITHFUL)
                else:
                    run.flag("unfaithful")
                    run.warnings.append(WARNING_UNFAITHFUL)

        # Section-number verifier: every "Section X" must be in the sources or section_mappings.
        known = {s.chunk.section_number for s in sources}
        missing = [n for n in mentioned_sections(answer) if n not in known]
        if missing:
            known |= await self._store.mapped_sections(missing)
            for number in (n for n in missing if n not in known):
                run.flag("unverified_section")
                run.warnings.append(
                    f"Section {number} is mentioned in the answer but could not be verified "
                    "against the retrieved sources."
                )
        return answer, cited

    async def _regenerate(
        self, run: _Run, sources: list[Source], claims: Sequence[str]
    ) -> str | None:
        extra = STRICT_RETRY_INSTRUCTION.format(
            claims="\n".join(f"- {c}" for c in claims) or "- (unspecified)"
        )
        request = self._answer_request(run.query, sources, extra=extra, purpose="answer_retry")
        try:
            response = await self._llm.complete(request)
        except LLMError:
            logger.warning("answer_regeneration_failed", exc_info=True)
            return None
        run.usage.add(response, "answer_retry")
        return response.text

    def _answer_request(
        self,
        question: str,
        sources: list[Source],
        *,
        extra: str | None = None,
        purpose: str = "answer",
    ) -> LLMRequest:
        return LLMRequest(
            messages=answer_messages(ANSWER_SYSTEM_PROMPT, question, sources, extra=extra),
            max_tokens=self._settings.answer_max_tokens,
            temperature=self._settings.answer_temperature,
            purpose=purpose,
        )

    # ---------------------------------------------------------------- endings
    async def _refuse(self, run: _Run, reason: str) -> ResultEvent:
        run.flag(reason)
        answer = REFUSALS[reason]
        response = QueryResponse(
            answer=answer,
            citations=[],
            refused=True,
            refusal_reason=reason,
            warnings=run.warnings,
            latency_ms=run.latency_ms,
        )
        response.query_log_id = await self._log(run, answer=answer, refused=True, reason=reason)
        return ResultEvent(response)

    async def _from_cache(self, run: _Run, cached: dict[str, object]) -> QueryResponse:
        response = QueryResponse.model_validate(
            {**cached, "refused": False, "latency_ms": run.latency_ms, "cache_hit": True}
        )
        response.query_log_id = await self._log(
            run, answer=response.answer, refused=False, cache_hit=True
        )
        return response

    async def _log(
        self,
        run: _Run,
        *,
        answer: str | None,
        refused: bool,
        reason: str | None = None,
        cache_hit: bool = False,
    ) -> uuid.UUID | None:
        entry = QueryLogEntry(
            user_id=run.user_id,
            query=run.query,
            rewritten_query=" | ".join(run.rewritten) or None,
            retrieved_chunk_ids=run.chunk_ids,
            answer=answer,
            refused=refused,
            refusal_reason=reason,
            guardrail_flags=list(run.flags),
            latency_ms=run.latency_ms,
            prompt_tokens=run.usage.prompt_tokens,
            completion_tokens=run.usage.completion_tokens,
            provider=run.usage.provider,
            model=run.usage.model,
            cache_hit=cache_hit,
        )
        try:
            return await self._store.log(entry)
        except Exception:  # a logging failure must not hide the answer
            logger.exception("query_log_failed")
            return None


def _citation(source: Source) -> Citation:
    chunk = source.chunk
    text = " ".join(chunk.text.split())
    return Citation(
        n=source.n,
        act=chunk.act_code,
        act_status=chunk.act_status,
        section_number=chunk.section_number,
        section_title=chunk.section_title,
        page_start=chunk.page_start,
        snippet=text if len(text) <= _SNIPPET_CHARS else text[:_SNIPPET_CHARS] + "…",
    )


def final_response(events: Sequence[QueryEvent]) -> QueryResponse:
    for event in reversed(events):
        if isinstance(event, ResultEvent):
            return event.response
    raise RuntimeError("pipeline ended without a result")  # pragma: no cover


__all__ = [
    "REFUSALS",
    "QueryEvent",
    "QueryPipeline",
    "ResultEvent",
    "StatusEvent",
    "TokenEvent",
    "final_response",
]
