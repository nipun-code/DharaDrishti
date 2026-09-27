"""Background ingestion: extract -> clean -> chunk -> embed -> replace the act's chunks.

Progress (0-100) and status are committed after each stage so GET /documents/{id} can show them.
The final swap (delete the act's previous version, insert the new chunks, mark ready) happens in
a single transaction, so searches never see a half-replaced act.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import Act, Document, DocumentStatus
from app.db.models.types import EMBEDDING_DIM
from app.repositories.documents import DocumentRepository
from app.services.ingestion.embedder import Embedder
from app.services.ingestion.legal_chunker import chunk_act
from app.services.ingestion.pdf_parser import clean_pages, extract_pages
from app.services.ingestion.storage import DocumentStorage
from app.services.ingestion.types import ChunkDraft, IngestionError, PageText

logger = logging.getLogger(__name__)

PdfReader = Callable[[Path], list[PageText]]

# Progress milestones (percent).
_STARTED, _EXTRACTED, _CHUNKED, _EMBEDDED = 5, 15, 25, 90

UNEXPECTED_ERROR = "Unexpected error while processing the document. See worker logs."


class IngestionPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        storage: DocumentStorage,
        settings: Settings,
        read_pdf: PdfReader = extract_pages,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._storage = storage
        self._settings = settings
        self._read_pdf = read_pdf

    async def run(self, document_id: uuid.UUID) -> None:
        log_extra = {"document_id": str(document_id)}
        act_code = await self._start(document_id)
        if act_code is None:
            return
        logger.info("ingestion_started", extra=log_extra)
        try:
            chunks = await self._ingest(document_id, act_code)
        except IngestionError as exc:
            logger.warning("ingestion_failed", extra={**log_extra, "reason": str(exc)})
            await self._update(document_id, status=DocumentStatus.FAILED, error=str(exc))
        except Exception:
            logger.exception("ingestion_crashed", extra=log_extra)
            await self._update(document_id, status=DocumentStatus.FAILED, error=UNEXPECTED_ERROR)
        else:
            logger.info("ingestion_finished", extra={**log_extra, "chunks": chunks})

    async def _start(self, document_id: uuid.UUID) -> str | None:
        """Mark the document as processing; return its act code, or None to skip."""
        async with self._session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None:
                logger.warning(
                    "ingestion_document_missing", extra={"document_id": str(document_id)}
                )
                return None
            if document.status == DocumentStatus.READY:
                return None  # a retried job for work that already finished
            act = await session.get(Act, document.act_id)
            assert act is not None  # noqa: S101  # FK guarantees it
            document.status = DocumentStatus.PROCESSING
            document.progress = _STARTED
            document.error = None
            await session.commit()
            return act.short_code

    async def _ingest(self, document_id: uuid.UUID, act_code: str) -> int:
        path = self._storage.path_for(document_id)
        if not path.exists():
            raise IngestionError("The uploaded file is missing from storage. Upload it again.")

        pages = clean_pages(await asyncio.to_thread(self._read_pdf, path))
        await self._update(document_id, pages=len(pages), progress=_EXTRACTED)

        drafts = await asyncio.to_thread(
            chunk_act,
            pages,
            act_code,
            self._embedder.count_tokens,
            max_tokens=self._settings.chunk_max_tokens,
            overlap_tokens=self._settings.chunk_overlap_tokens,
        )
        if not drafts:
            raise IngestionError(
                "No sections were detected. Expected bare-act headings like "
                "'12. Section title.—Text...'."
            )
        await self._update(document_id, progress=_CHUNKED)

        vectors = await self._embed(document_id, drafts)
        await self._swap_in(document_id, drafts, vectors)
        return len(drafts)

    async def _embed(
        self, document_id: uuid.UUID, drafts: Sequence[ChunkDraft]
    ) -> list[list[float]]:
        size = self._settings.embedding_batch_size
        batches = [drafts[i : i + size] for i in range(0, len(drafts), size)]
        vectors: list[list[float]] = []
        for done, batch in enumerate(batches, start=1):
            texts = [draft.embedding_text for draft in batch]
            vectors.extend(await asyncio.to_thread(self._embedder.embed, texts))
            progress = _CHUNKED + (_EMBEDDED - _CHUNKED) * done // len(batches)
            await self._update(document_id, progress=progress)
        if len(vectors) != len(drafts) or any(len(v) != EMBEDDING_DIM for v in vectors):
            raise IngestionError(
                f"Embedding model returned unexpected vectors (need {EMBEDDING_DIM}-d)."
            )
        return vectors

    async def _swap_in(
        self,
        document_id: uuid.UUID,
        drafts: Sequence[ChunkDraft],
        vectors: Sequence[list[float]],
    ) -> None:
        async with self._session_factory() as session, session.begin():
            documents = DocumentRepository(session)
            document = await session.get(Document, document_id, with_for_update=True)
            if document is None:  # deleted while we were working
                logger.info("ingestion_document_deleted", extra={"document_id": str(document_id)})
                return
            # Row lock on the act serializes concurrent replacements of the same act.
            act = await session.get(Act, document.act_id, with_for_update=True)
            assert act is not None  # noqa: S101
            superseded = await documents.delete_superseded(act.id, keep_id=document.id)
            await documents.replace_chunks(document.id, _rows(document, drafts, vectors))
            document.status = DocumentStatus.READY
            document.progress = 100
            document.chunks_count = len(drafts)
            document.error = None
            act.source_file = document.filename
        for old_id in superseded:
            await self._storage.delete(old_id)
        if superseded:
            logger.info(
                "act_version_replaced",
                extra={"act": act.short_code, "removed_documents": [str(i) for i in superseded]},
            )

    async def _update(self, document_id: uuid.UUID, **values: Any) -> None:
        async with self._session_factory() as session:
            await DocumentRepository(session).update_fields(document_id, **values)
            await session.commit()


def _rows(
    document: Document, drafts: Sequence[ChunkDraft], vectors: Sequence[list[float]]
) -> list[dict[str, Any]]:
    return [
        {
            "document_id": document.id,
            "act_id": document.act_id,
            "chapter_number": draft.chapter_number,
            "chapter_title": draft.chapter_title,
            "section_number": draft.section_number,
            "section_title": draft.section_title,
            "subsection": draft.subsection,
            "text": draft.text,
            "page_start": draft.page_start,
            "page_end": draft.page_end,
            "token_count": draft.token_count,
            "embedding": vector,
        }
        for draft, vector in zip(drafts, vectors, strict=True)
    ]
