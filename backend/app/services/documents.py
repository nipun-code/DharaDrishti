"""Document upload, status and deletion (the synchronous half of ingestion)."""

import logging
import re
import unicodedata
import uuid
from pathlib import PurePosixPath

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
)
from app.db.models import Act, ActStatus, Document, DocumentStatus
from app.repositories.acts import ActRepository
from app.repositories.documents import DocumentRepository
from app.schemas.documents import ActUpsert, DocumentRead
from app.services.ingestion.storage import AsyncReader, DocumentStorage, StagedUpload
from app.workers.queue import JobQueue

logger = logging.getLogger(__name__)

PDF_MIME_TYPES = frozenset({"application/pdf", "application/x-pdf"})
GENERIC_MIME_TYPES = frozenset({"application/octet-stream", "binary/octet-stream"})
PDF_MAGIC = b"%PDF-"
_MAX_FILENAME = 255
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\- ()]+")


def sanitize_filename(raw: str | None) -> str:
    """Keep only a safe base name (no directories, control or shell characters), ending .pdf."""
    name = PurePosixPath((raw or "").replace("\\", "/")).name
    name = unicodedata.normalize("NFKC", name)
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    stem = _UNSAFE_FILENAME_CHARS.sub("_", stem).strip(" ._") or "document"
    return f"{stem[: _MAX_FILENAME - 4]}.pdf"


def _check_pdf_magic(staged: StagedUpload) -> None:
    if not staged.head.startswith(PDF_MAGIC):
        raise UnsupportedMediaTypeError("The file is not a valid PDF.")


def to_read(document: Document, act_code: str) -> DocumentRead:
    return DocumentRead(
        id=document.id,
        act_short_code=act_code,
        filename=document.filename,
        status=document.status,
        progress=document.progress,
        error=document.error,
        pages=document.pages,
        chunks_count=document.chunks_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


class DocumentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: DocumentStorage,
        queue: JobQueue,
        settings: Settings,
    ) -> None:
        self._session = session
        self._acts = ActRepository(session)
        self._documents = DocumentRepository(session)
        self._storage = storage
        self._queue = queue
        self._settings = settings

    # ---------------------------------------------------------------- upload
    async def upload(
        self,
        reader: AsyncReader,
        filename: str | None,
        content_type: str | None,
        act_meta: ActUpsert,
    ) -> Document:
        clean_name = sanitize_filename(filename)
        self._check_content_type(content_type, filename)
        act = await self._acts.get_by_short_code(act_meta.act_short_code)
        if act is None and (act_meta.act_full_name is None or act_meta.act_year is None):
            raise BadRequestError(
                f"Act {act_meta.act_short_code} does not exist yet: "
                "act_full_name and act_year are required to create it."
            )

        staged = await self._storage.stage(reader, self._settings.max_upload_bytes)
        document: Document | None = None
        replaced_failed: uuid.UUID | None = None
        try:
            _check_pdf_magic(staged)
            replaced_failed = await self._reject_duplicate(staged)
            act = await self._upsert_act(act, act_meta)
            document = await self._documents.add(
                Document(act_id=act.id, filename=clean_name, sha256=staged.sha256)
            )
            await self._storage.commit(staged, document.id)
            await self._session.commit()
        except IntegrityError as exc:  # concurrent upload of the same file won the race
            await self._cleanup_failed_upload(staged, document)
            raise ConflictError("This exact file has already been uploaded.") from exc
        except BaseException:
            await self._cleanup_failed_upload(staged, document)
            raise

        if replaced_failed is not None:
            await self._storage.delete(replaced_failed)
        logger.info(
            "document_uploaded",
            extra={"document_id": str(document.id), "act": act.short_code, "bytes": staged.size},
        )
        await self._enqueue(document)
        return document

    def _check_content_type(self, content_type: str | None, filename: str | None) -> None:
        mime = (content_type or "").split(";")[0].strip().lower()
        if mime in PDF_MIME_TYPES:
            return
        # Some clients send a generic type; accept it only for a .pdf name (magic bytes decide).
        if mime in GENERIC_MIME_TYPES and (filename or "").lower().endswith(".pdf"):
            return
        raise UnsupportedMediaTypeError("Only PDF files (application/pdf) can be uploaded.")

    async def _reject_duplicate(self, staged: StagedUpload) -> uuid.UUID | None:
        """409 for an identical file, unless the earlier attempt failed: then allow a retry
        by removing the failed record. Returns the removed document id, if any."""
        existing = await self._documents.get_by_sha256(staged.sha256)
        if existing is None:
            return None
        if existing.status != DocumentStatus.FAILED:
            raise ConflictError(
                "This exact file has already been uploaded.",
                details={"document_id": str(existing.id)},
            )
        await self._documents.delete(existing)
        return existing.id

    async def _upsert_act(self, act: Act | None, meta: ActUpsert) -> Act:
        if act is None:
            assert meta.act_full_name is not None  # noqa: S101  # checked in upload()
            assert meta.act_year is not None  # noqa: S101
            return await self._acts.add(
                Act(
                    short_code=meta.act_short_code,
                    full_name=meta.act_full_name,
                    year=meta.act_year,
                    status=meta.act_status or ActStatus.IN_FORCE,
                )
            )
        if meta.act_full_name is not None:
            act.full_name = meta.act_full_name
        if meta.act_year is not None:
            act.year = meta.act_year
        if meta.act_status is not None:
            act.status = meta.act_status
        return act

    async def _cleanup_failed_upload(self, staged: StagedUpload, document: Document | None) -> None:
        await self._session.rollback()
        await self._storage.discard(staged)
        if document is not None:
            await self._storage.delete(document.id)

    async def _enqueue(self, document: Document) -> None:
        try:
            await self._queue.enqueue_ingestion(document.id)
        except Exception as exc:
            logger.exception("ingestion_enqueue_failed", extra={"document_id": str(document.id)})
            document.status = DocumentStatus.FAILED
            document.error = "Could not queue the ingestion job. Please upload the file again."
            await self._session.commit()
            raise ServiceUnavailableError(
                "The ingestion queue is unavailable. Please try again shortly."
            ) from exc

    # ---------------------------------------------------------------- queries
    async def get(self, document_id: uuid.UUID) -> DocumentRead:
        found = await self._documents.get_with_act_code(document_id)
        if found is None:
            raise NotFoundError("Document not found.")
        return to_read(*found)

    async def list(self, *, limit: int, offset: int) -> list[DocumentRead]:
        rows = await self._documents.list_with_act_code(limit=limit, offset=offset)
        return [to_read(doc, code) for doc, code in rows]

    async def delete(self, document_id: uuid.UUID) -> None:
        document = await self._documents.get(document_id)
        if document is None:
            raise NotFoundError("Document not found.")
        await self._documents.delete(document)  # chunks cascade
        await self._session.commit()
        await self._storage.delete(document_id)
        logger.info("document_deleted", extra={"document_id": str(document_id)})
