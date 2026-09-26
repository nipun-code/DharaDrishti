from sqlalchemy import select

from app.db.models import EvalRun
from app.repositories.base import BaseRepository


class EvalRunRepository(BaseRepository[EvalRun]):
    model = EvalRun

    async def list_recent(self, *, limit: int = 20) -> list[EvalRun]:
        stmt = select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit)
        return list(await self._session.scalars(stmt))
