"""Search backend: each call opens its own session so keyword and vector searches (and
searches for several query variants) can run concurrently. An AsyncSession must never be
shared between concurrent tasks."""

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.chunk_search import ChunkSearchRepository
from app.services.retrieval.types import ChunkHit, ChunkRecord


class SearchBackend(Protocol):
    async def keyword(
        self, query: str, act_codes: Sequence[str] | None, limit: int
    ) -> list[ChunkHit]: ...

    async def vector(
        self, embedding: Sequence[float], act_codes: Sequence[str] | None, limit: int
    ) -> list[ChunkHit]: ...

    async def section(
        self, act_code: str, section: str, subsection: str | None, limit: int
    ) -> list[ChunkRecord]: ...

    async def mappings(self, from_act: str, section: str) -> list[tuple[str, str]]: ...


class PostgresSearchBackend:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, ef_search: int = 100
    ) -> None:
        self._session_factory = session_factory
        self._ef_search = ef_search

    async def keyword(
        self, query: str, act_codes: Sequence[str] | None, limit: int
    ) -> list[ChunkHit]:
        async with self._session_factory() as session:
            return await ChunkSearchRepository(session).keyword_search(query, act_codes, limit)

    async def vector(
        self, embedding: Sequence[float], act_codes: Sequence[str] | None, limit: int
    ) -> list[ChunkHit]:
        async with self._session_factory() as session, session.begin():
            return await ChunkSearchRepository(session).vector_search(
                embedding, act_codes, limit, self._ef_search
            )

    async def section(
        self, act_code: str, section: str, subsection: str | None, limit: int
    ) -> list[ChunkRecord]:
        async with self._session_factory() as session:
            return await ChunkSearchRepository(session).section_chunks(
                act_code, section, subsection, limit
            )

    async def mappings(self, from_act: str, section: str) -> list[tuple[str, str]]:
        async with self._session_factory() as session:
            return await ChunkSearchRepository(session).mapping_targets(from_act, section)
