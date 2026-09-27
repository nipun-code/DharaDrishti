"""Persistence used by the query pipeline: query logs and mapped-section checks.
Opens its own sessions, so it is safe to use from inside a streaming response."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import QueryLog, SectionMapping


@dataclass(slots=True)
class QueryLogEntry:
    user_id: uuid.UUID | None
    query: str  # PII-redacted
    rewritten_query: str | None = None
    retrieved_chunk_ids: list[int] = field(default_factory=list)
    answer: str | None = None
    refused: bool = False
    refusal_reason: str | None = None
    guardrail_flags: list[str] = field(default_factory=list)
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    provider: str | None = None
    model: str | None = None
    cache_hit: bool = False


class QueryStore(Protocol):
    async def log(self, entry: QueryLogEntry) -> uuid.UUID: ...

    async def mapped_sections(self, numbers: Iterable[str]) -> set[str]: ...


class PostgresQueryStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def log(self, entry: QueryLogEntry) -> uuid.UUID:
        values: dict[str, Any] = {
            name: getattr(entry, name) for name in QueryLogEntry.__dataclass_fields__
        }
        row = QueryLog(**values)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return row.id

    async def mapped_sections(self, numbers: Iterable[str]) -> set[str]:
        """Which of `numbers` appear (as base section numbers) in section_mappings."""
        wanted = sorted(set(numbers))
        if not wanted:
            return set()
        base_from = func.regexp_replace(SectionMapping.from_section, r"\(.*$", "")
        base_to = func.regexp_replace(SectionMapping.to_section, r"\(.*$", "")
        stmt = select(base_from, base_to).where(or_(base_from.in_(wanted), base_to.in_(wanted)))
        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).all()
        found = {value for row in rows for value in row}
        return found & set(wanted)
