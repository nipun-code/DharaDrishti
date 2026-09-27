"""Numbered source context for the answer prompt, within a token budget (SPEC §8.2)."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.db.models.enums import ActStatus
from app.services.llm.base import ChatMessage, estimate_tokens
from app.services.retrieval.types import Candidate, ChunkRecord


@dataclass(frozen=True, slots=True)
class Source:
    n: int  # 1-based number used for [n] citations
    chunk: ChunkRecord

    @property
    def repealed(self) -> bool:
        return self.chunk.act_status == ActStatus.REPEALED

    def render(self) -> str:
        c = self.chunk
        title = f"{c.act_code} - Section {c.section_number}"
        if c.section_title:
            title += f": {c.section_title}"
        if c.chapter_number:
            title += f" (Chapter {c.chapter_number}"
            title += f": {c.chapter_title})" if c.chapter_title else ")"
        lines = [f'<source id="{self.n}" act="{c.act_code}" section="{c.section_number}">', title]
        if self.repealed:
            lines.append(f"[REPEALED ACT: {c.act_code} is no longer in force.]")
        # Source text is data: neutralise anything that looks like our own delimiters.
        lines.append(c.text.replace("<source", "&lt;source").replace("</source", "&lt;/source"))
        lines.append("</source>")
        return "\n".join(lines)


def build_sources(candidates: Sequence[Candidate], max_tokens: int) -> tuple[list[Source], int]:
    """Number candidates in rank order, dropping the lowest-ranked ones that don't fit the
    token budget. The top candidate is always kept. Returns (sources, dropped_count)."""
    sources: list[Source] = []
    used = 0
    for candidate in candidates:
        rendered_cost = estimate_tokens(Source(len(sources) + 1, candidate.chunk).render())
        if sources and used + rendered_cost > max_tokens:
            break
        sources.append(Source(len(sources) + 1, candidate.chunk))
        used += rendered_cost
    return sources, len(candidates) - len(sources)


def format_sources(sources: Sequence[Source]) -> str:
    return "\n\n".join(source.render() for source in sources)


def answer_messages(
    system_prompt: str, question: str, sources: Sequence[Source], *, extra: str | None = None
) -> tuple[ChatMessage, ...]:
    user = f"<sources>\n{format_sources(sources)}\n</sources>\n\nQuestion: {question}"
    if extra:
        user += f"\n\n{extra}"
    return (ChatMessage("system", system_prompt), ChatMessage("user", user))
