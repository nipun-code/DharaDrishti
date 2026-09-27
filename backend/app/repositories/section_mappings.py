from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

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

    async def upsert_many(self, rows: Sequence[dict[str, Any]]) -> None:
        """Insert rows; on an existing (from, to) pair, update its note."""
        if not rows:
            return
        stmt = insert(SectionMapping).values(list(rows))
        stmt = stmt.on_conflict_do_update(
            constraint="uq_section_mappings_from_to", set_={"note": stmt.excluded.note}
        )
        await self._session.execute(stmt)

    async def delete_all(self) -> int:
        result = await self._session.execute(delete(SectionMapping))
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
