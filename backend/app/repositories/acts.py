from sqlalchemy import func, select

from app.db.models import Act, Chunk
from app.repositories.base import BaseRepository


class ActRepository(BaseRepository[Act]):
    model = Act

    async def get_by_short_code(self, short_code: str) -> Act | None:
        return await self._session.scalar(select(Act).where(Act.short_code == short_code))

    async def list_all(self) -> list[Act]:
        result = await self._session.scalars(select(Act).order_by(Act.short_code))
        return list(result)

    async def list_with_chunk_counts(self) -> list[tuple[Act, int]]:
        stmt = (
            select(Act, func.count(Chunk.id))
            .outerjoin(Chunk, Chunk.act_id == Act.id)
            .group_by(Act.id)
            .order_by(Act.status, Act.short_code)
        )
        return [(act, int(count)) for act, count in (await self._session.execute(stmt)).all()]
