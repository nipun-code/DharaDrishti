"""Chunk persistence. Keyword/vector search queries are added with the retrieval phase."""

from sqlalchemy import select

from app.db.models import Chunk
from app.repositories.base import BaseRepository


class ChunkRepository(BaseRepository[Chunk]):
    model = Chunk

    async def list_for_section(self, act_id: int, section_number: str) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.act_id == act_id, Chunk.section_number == section_number)
            .order_by(Chunk.id)
        )
        return list(await self._session.scalars(stmt))
