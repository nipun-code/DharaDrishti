from sqlalchemy import select

from app.db.models import Document
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def get_by_sha256(self, sha256: str) -> Document | None:
        return await self._session.scalar(select(Document).where(Document.sha256 == sha256))

    async def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[Document]:
        stmt = select(Document).order_by(Document.created_at.desc()).limit(limit).offset(offset)
        return list(await self._session.scalars(stmt))
