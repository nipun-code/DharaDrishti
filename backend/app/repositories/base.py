"""Generic async repository. Repositories flush but never commit: services own transactions."""

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):  # PEP 695 syntax needs Python 3.12
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id_: Any) -> ModelT | None:
        return await self._session.get(self.model, id_)

    async def add(self, obj: ModelT) -> ModelT:
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def add_all(self, objs: Sequence[ModelT]) -> None:
        self._session.add_all(objs)
        await self._session.flush()

    async def delete(self, obj: ModelT) -> None:
        await self._session.delete(obj)
        await self._session.flush()
