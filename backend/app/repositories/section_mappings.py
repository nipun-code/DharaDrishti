from sqlalchemy import select

from app.db.models import SectionMapping
from app.repositories.base import BaseRepository


class SectionMappingRepository(BaseRepository[SectionMapping]):
    model = SectionMapping

    async def list_from(self, from_act: str, from_section: str) -> list[SectionMapping]:
        stmt = (
            select(SectionMapping)
            .where(SectionMapping.from_act == from_act, SectionMapping.from_section == from_section)
            .order_by(SectionMapping.id)
        )
        return list(await self._session.scalars(stmt))
