"""Read-side chunk queries used by retrieval: keyword, vector and exact-section lookups."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Row, case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Act, ActStatus, Chunk, SectionMapping
from app.services.retrieval.types import ChunkHit, ChunkRecord

# Everything except the (large) embedding and the tsvector.
_CHUNK_COLUMNS = (
    Chunk.id,
    Act.short_code,
    Act.status,
    Chunk.chapter_number,
    Chunk.chapter_title,
    Chunk.section_number,
    Chunk.section_title,
    Chunk.subsection,
    Chunk.text,
    Chunk.page_start,
    Chunk.page_end,
)


def act_filter_clause(act_codes: Sequence[str] | None) -> ColumnElement[bool]:
    """Explicit act codes (repealed acts allowed), else every in-force act."""
    if act_codes:
        return Act.short_code.in_(list(act_codes))
    return Act.status == ActStatus.IN_FORCE


def _record(row: Row[Any] | Any) -> ChunkRecord:
    return ChunkRecord(
        id=row.id,
        act_code=row.short_code,
        act_status=ActStatus(row.status),
        chapter_number=row.chapter_number,
        chapter_title=row.chapter_title,
        section_number=row.section_number,
        section_title=row.section_title,
        subsection=row.subsection,
        text=row.text,
        page_start=row.page_start,
        page_end=row.page_end,
    )


class ChunkSearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def keyword_search(
        self, query: str, act_codes: Sequence[str] | None, limit: int
    ) -> list[ChunkHit]:
        """Full-text search: websearch_to_tsquery (quotes, OR, -negation) ranked by ts_rank_cd."""
        tsquery = func.websearch_to_tsquery("english", query)
        rank = func.ts_rank_cd(Chunk.tsv, tsquery)
        stmt = (
            select(*_CHUNK_COLUMNS, rank.label("score"))
            .join(Act, Act.id == Chunk.act_id)
            .where(Chunk.tsv.op("@@")(tsquery), act_filter_clause(act_codes))
            .order_by(rank.desc(), Chunk.id)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [ChunkHit(_record(row), float(row.score)) for row in rows]

    async def vector_search(
        self,
        embedding: Sequence[float],
        act_codes: Sequence[str] | None,
        limit: int,
        ef_search: int,
    ) -> list[ChunkHit]:
        """Nearest neighbours by cosine distance via the HNSW index.

        Must run inside a transaction: the SET LOCALs below tune this query only.
        Iterative scanning (pgvector >= 0.8) keeps searching when the act filter removes
        rows, so a selective filter still returns `limit` results.
        """
        await self._session.execute(
            text("SELECT set_config('hnsw.ef_search', :ef, true)"), {"ef": str(ef_search)}
        )
        await self._session.execute(
            text("SELECT set_config('hnsw.iterative_scan', 'strict_order', true)")
        )
        distance = Chunk.embedding.cosine_distance(list(embedding))
        stmt = (
            select(*_CHUNK_COLUMNS, (1 - distance).label("score"))
            .join(Act, Act.id == Chunk.act_id)
            .where(act_filter_clause(act_codes))
            .order_by(distance)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [ChunkHit(_record(row), float(row.score)) for row in rows]

    async def section_chunks(
        self, act_code: str, section: str, subsection: str | None, limit: int
    ) -> list[ChunkRecord]:
        """Chunks of one section, pieces matching the requested sub-section first."""
        order: list[Any] = []
        if subsection:
            order.append(case((Chunk.subsection == subsection, 0), else_=1))
        order.append(Chunk.id)
        stmt = (
            select(*_CHUNK_COLUMNS)
            .join(Act, Act.id == Chunk.act_id)
            .where(Act.short_code == act_code, Chunk.section_number == section)
            .order_by(*order)
            .limit(limit)
        )
        return [_record(row) for row in (await self._session.execute(stmt)).all()]

    async def mapping_targets(self, from_act: str, section: str) -> list[tuple[str, str]]:
        """(to_act, to_section) rows for a section, including sub-section-level rows
        such as from_section "420(1)" when asked for "420"."""
        stmt = (
            select(SectionMapping.to_act, SectionMapping.to_section)
            .where(
                SectionMapping.from_act == from_act,
                or_(
                    SectionMapping.from_section == section,
                    SectionMapping.from_section.like(f"{section}(%"),
                ),
            )
            .order_by(SectionMapping.id)
        )
        return [(row.to_act, row.to_section) for row in (await self._session.execute(stmt)).all()]
