import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, insert, select, update

from app.db.models import Act, Chunk, Document, DocumentStatus
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def get_by_sha256(self, sha256: str) -> Document | None:
        return await self._session.scalar(select(Document).where(Document.sha256 == sha256))

    async def get_with_act_code(self, document_id: uuid.UUID) -> tuple[Document, str] | None:
        stmt = (
            select(Document, Act.short_code)
            .join(Act, Act.id == Document.act_id)
            .where(Document.id == document_id)
        )
        row = (await self._session.execute(stmt)).one_or_none()
        return (row[0], row[1]) if row else None

    async def list_with_act_code(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[tuple[Document, str]]:
        stmt = (
            select(Document, Act.short_code)
            .join(Act, Act.id == Document.act_id)
            .order_by(Document.created_at.desc(), Document.id)
            .limit(limit)
            .offset(offset)
        )
        return [(doc, code) for doc, code in (await self._session.execute(stmt)).all()]

    async def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[Document]:
        stmt = select(Document).order_by(Document.created_at.desc()).limit(limit).offset(offset)
        return list(await self._session.scalars(stmt))

    async def update_fields(self, document_id: uuid.UUID, **values: Any) -> None:
        await self._session.execute(
            update(Document).where(Document.id == document_id).values(**values)
        )

    async def delete_superseded(self, act_id: int, keep_id: uuid.UUID) -> list[uuid.UUID]:
        """Delete the act's other *finished* documents (chunks cascade). In-flight uploads are
        left alone; whichever finishes last becomes the act's current version."""
        stmt = (
            delete(Document)
            .where(
                Document.act_id == act_id,
                Document.id != keep_id,
                Document.status.in_([DocumentStatus.READY, DocumentStatus.FAILED]),
            )
            .returning(Document.id)
            .execution_options(synchronize_session=False)
        )
        return list(await self._session.scalars(stmt))

    async def replace_chunks(self, document_id: uuid.UUID, rows: Sequence[dict[str, Any]]) -> None:
        await self._session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        if rows:
            await self._session.execute(insert(Chunk), list(rows))
