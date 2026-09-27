"""Local storage for uploaded PDFs (a directory shared by the API and the worker)."""

import asyncio
import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.exceptions import BadRequestError, PayloadTooLargeError

_READ_CHUNK = 1024 * 1024
_HEAD_BYTES = 8


class AsyncReader(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class StagedUpload:
    """An upload written to a temp file, hashed and size-checked, not yet named after its row."""

    path: Path
    sha256: str
    size: int
    head: bytes  # first bytes, for magic-number checks


class DocumentStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, document_id: uuid.UUID) -> Path:
        return self.root / f"{document_id}.pdf"

    async def stage(self, reader: AsyncReader, max_bytes: int) -> StagedUpload:
        """Stream `reader` to a temp file, computing sha256 and enforcing `max_bytes`."""
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        fd, name = await asyncio.to_thread(
            tempfile.mkstemp, dir=self.root, prefix=".upload-", suffix=".part"
        )
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as out:
                return await _copy_checked(reader, out, path, max_bytes)
        except BaseException:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise

    async def commit(self, staged: StagedUpload, document_id: uuid.UUID) -> Path:
        destination = self.path_for(document_id)
        await asyncio.to_thread(os.replace, staged.path, destination)
        return destination

    async def discard(self, staged: StagedUpload) -> None:
        await asyncio.to_thread(staged.path.unlink, missing_ok=True)

    async def delete(self, document_id: uuid.UUID) -> None:
        await asyncio.to_thread(self.path_for(document_id).unlink, missing_ok=True)


async def _copy_checked(
    reader: AsyncReader, out: BinaryIO, path: Path, max_bytes: int
) -> StagedUpload:
    digest = hashlib.sha256()
    size = 0
    head = b""
    while chunk := await reader.read(_READ_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            raise PayloadTooLargeError(
                f"The file exceeds the {max_bytes // (1024 * 1024)} MB upload limit."
            )
        if len(head) < _HEAD_BYTES:
            head = (head + chunk)[:_HEAD_BYTES]
        digest.update(chunk)
        await asyncio.to_thread(out.write, chunk)
    if size == 0:
        raise BadRequestError("The uploaded file is empty.")
    return StagedUpload(path=path, sha256=digest.hexdigest(), size=size, head=head)
