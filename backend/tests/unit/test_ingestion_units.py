"""Unit tests for upload helpers, storage, the embedder wrapper and the size-limit middleware."""

import hashlib
import io
import sys
import types
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import BadRequestError, PayloadTooLargeError, UnsupportedMediaTypeError
from app.db.models.types import EMBEDDING_DIM
from app.services.documents import DocumentService, sanitize_filename
from app.services.ingestion.embedder import SentenceTransformerEmbedder
from app.services.ingestion.storage import DocumentStorage
from app.services.ingestion.types import IngestionError
from tests.conftest import FakeJobQueue


class BytesReader:
    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


# ---------------------------------------------------------------- filenames & mime
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("act.pdf", "act.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\me\\Bare Act (2023).PDF", "Bare Act (2023).pdf"),
        ("rm -rf; $(evil).pdf", "rm -rf_ _(evil).pdf"),
        ("no_extension", "no_extension.pdf"),
        ("", "document.pdf"),
        (None, "document.pdf"),
        ("....pdf", "document.pdf"),
        ("a" * 400 + ".pdf", "a" * 251 + ".pdf"),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize(
    ("content_type", "filename"),
    [
        ("application/pdf", "x.pdf"),
        ("application/pdf; charset=binary", "x.pdf"),
        ("application/x-pdf", "x"),
        ("application/octet-stream", "act.PDF"),
    ],
)
def test_accepted_content_types(settings: Settings, content_type: str, filename: str) -> None:
    service = DocumentService(None, None, FakeJobQueue(), settings)  # type: ignore[arg-type]
    service._check_content_type(content_type, filename)


@pytest.mark.parametrize(
    ("content_type", "filename"),
    [("text/plain", "x.pdf"), ("application/octet-stream", "x.txt"), (None, "x.pdf")],
)
def test_rejected_content_types(
    settings: Settings, content_type: str | None, filename: str
) -> None:
    service = DocumentService(None, None, FakeJobQueue(), settings)  # type: ignore[arg-type]
    with pytest.raises(UnsupportedMediaTypeError):
        service._check_content_type(content_type, filename)


# ---------------------------------------------------------------- storage
async def test_stage_hashes_and_commits(tmp_path: Path) -> None:
    storage = DocumentStorage(tmp_path / "up")
    data = b"%PDF-1.7 placeholder bytes" * 1000

    staged = await storage.stage(BytesReader(data), max_bytes=len(data))

    assert staged.sha256 == hashlib.sha256(data).hexdigest()
    assert staged.size == len(data)
    assert staged.head == data[:8]
    doc_id = uuid.uuid4()
    final = await storage.commit(staged, doc_id)
    assert final == storage.path_for(doc_id)
    assert final.read_bytes() == data
    assert not staged.path.exists()

    await storage.delete(doc_id)
    assert not final.exists()


async def test_stage_rejects_oversized_and_cleans_up(tmp_path: Path) -> None:
    storage = DocumentStorage(tmp_path)

    with pytest.raises(PayloadTooLargeError):
        await storage.stage(BytesReader(b"x" * 101), max_bytes=100)

    assert list(tmp_path.iterdir()) == []


async def test_stage_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(BadRequestError, match="empty"):
        await DocumentStorage(tmp_path).stage(BytesReader(b""), max_bytes=10)
    assert list(tmp_path.iterdir()) == []


async def test_discard_and_delete_are_idempotent(tmp_path: Path) -> None:
    storage = DocumentStorage(tmp_path)
    staged = await storage.stage(BytesReader(b"%PDF-"), max_bytes=10)

    await storage.discard(staged)
    await storage.discard(staged)
    await storage.delete(uuid.uuid4())

    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- embedder wrapper
class _FakeTokenizer:
    def __call__(self, text: str, **_: Any) -> dict[str, list[int]]:
        return {"input_ids": list(range(len(text.split())))}


class _FakeModel:
    instances = 0

    def __init__(self, name: str, device: str, dim: int = EMBEDDING_DIM) -> None:
        _FakeModel.instances += 1
        self.name, self.device, self.dim = name, device, dim
        self.tokenizer = _FakeTokenizer()
        self.encode_kwargs: dict[str, Any] = {}

    def get_sentence_embedding_dimension(self) -> int:
        return self.dim

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.encode_kwargs = kwargs
        return [[0.5] * self.dim for _ in texts]


@pytest.fixture
def fake_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = _FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    _FakeModel.instances = 0
    return module


@pytest.mark.usefixtures("fake_sentence_transformers")
def test_embedder_loads_once_and_normalizes() -> None:
    embedder = SentenceTransformerEmbedder("some/model", batch_size=4, device="cpu")

    vectors = embedder.embed(["a b", "c"])
    tokens = embedder.count_tokens("one two three")

    assert len(vectors) == 2
    assert len(vectors[0]) == EMBEDDING_DIM
    assert tokens == 3
    assert _FakeModel.instances == 1
    assert embedder._model.encode_kwargs["normalize_embeddings"] is True
    assert embedder._model.encode_kwargs["batch_size"] == 4


@pytest.mark.usefixtures("fake_sentence_transformers")
def test_embedder_empty_input_skips_model() -> None:
    embedder = SentenceTransformerEmbedder("some/model")

    assert embedder.embed([]) == []
    assert _FakeModel.instances == 0


def test_embedder_rejects_wrong_dimension(fake_sentence_transformers: types.ModuleType) -> None:
    fake_sentence_transformers.SentenceTransformer = (  # type: ignore[attr-defined]
        lambda name, device: _FakeModel(name, device, dim=768)
    )

    with pytest.raises(IngestionError, match="768-d"):
        SentenceTransformerEmbedder("big/model").embed(["x"])


# ---------------------------------------------------------------- settings & middleware
def test_overlap_must_be_less_than_half_of_chunk(settings: Settings) -> None:
    with pytest.raises(ValidationError, match="CHUNK_OVERLAP_TOKENS"):
        Settings(**{**settings.model_dump(), "chunk_max_tokens": 100, "chunk_overlap_tokens": 60})


async def test_oversized_request_rejected_before_body_is_read(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    too_big = settings.max_upload_bytes + 2 * 1024 * 1024

    response = await client.post(
        "/api/v1/documents", content=b"x" * 10, headers={"Content-Length": str(too_big)}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.headers["X-Request-ID"]
