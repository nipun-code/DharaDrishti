from sqlalchemy import select

from app.db.models import Act
from app.repositories.base import BaseRepository


class ActRepository(BaseRepository[Act]):
    model = Act

    async def get_by_short_code(self, short_code: str) -> Act | None:
        return await self._session.scalar(select(Act).where(Act.short_code == short_code))

    async def list_all(self) -> list[Act]:
        result = await self._session.scalars(select(Act).order_by(Act.short_code))
        return list(result)
