"""End-to-end ingestion against real PostgreSQL with a fake embedder and synthetic PDF text."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import Act, Chunk, Document, DocumentStatus
from app.services.ingestion.pipeline import UNEXPECTED_ERROR, IngestionPipeline
from app.services.ingestion.storage import DocumentStorage
from app.services.ingestion.types import IngestionError, PageText
from tests.conftest import FakeEmbedder
from tests.fixtures.fake_act import FAKE_ACT_PAGES

pytestmark = pytest.mark.integration


class FakeReader:
    def __init__(self, pages: list[PageText] | Exception) -> None:
        self.pages = pages
        self.calls = 0

    def __call__(self, path: Path) -> list[PageText]:
        self.calls += 1
        assert path.exists()
        if isinstance(self.pages, Exception):
            raise self.pages
        return self.pages


@pytest.fixture
def storage(settings: Settings) -> DocumentStorage:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return DocumentStorage(settings.upload_dir)


def make_pipeline(
    factory: async_sessionmaker[AsyncSession],
    storage: DocumentStorage,
    settings: Settings,
    reader: FakeReader,
    embedder: FakeEmbedder | None = None,
) -> IngestionPipeline:
    return IngestionPipeline(factory, embedder or FakeEmbedder(), storage, settings, reader)


async def new_document(
    session: AsyncSession, storage: DocumentStorage, act_code: str = "TST", sha: str = "a"
) -> uuid.UUID:
    act = await session.scalar(select(Act).where(Act.short_code == act_code))
    if act is None:
        act = Act(short_code=act_code, full_name="Placeholder", year=2000)
        session.add(act)
        await session.flush()
    doc = Document(act_id=act.id, filename=f"{act_code}.pdf", sha256=sha * 64)
    session.add(doc)
    await session.commit()
    storage.path_for(doc.id).write_bytes(b"%PDF-1.7 placeholder")
    return doc.id


async def reload(session: AsyncSession, doc_id: uuid.UUID) -> Document | None:
    session.expunge_all()
    return await session.get(Document, doc_id)


# ---------------------------------------------------------------- happy path
async def test_ingests_fake_act(
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    storage: DocumentStorage,
    settings: Settings,
) -> None:
    doc_id = await new_document(db_session, storage)
    embedder = FakeEmbedder()

    await make_pipeline(
        session_factory, storage, settings, FakeReader(FAKE_ACT_PAGES), embedder
    ).run(doc_id)

    document = await reload(db_session, doc_id)
    assert document is not None
    assert (document.status, document.progress, document.error) == (DocumentStatus.READY, 100, None)
    assert document.pages == 4
    assert document.chunks_count == 6
    chunks = list(await db_session.scalars(select(Chunk).order_by(Chunk.id)))
    assert [c.section_number for c in chunks] == ["1", "2", "3", "4A", "5", "6"]
    assert chunks[2].chapter_title == "Of Placeholder Matters"
    # The embedded text includes the contextual header; the stored text does not.
    embedded = [t for batch in embedder.calls for t in batch]
    assert embedded[2].startswith("[TST | Chapter II: Of Placeholder Matters | Section 3:")
    assert not chunks[2].text.startswith("[")
    # Generated tsvector works for keyword search.
    hits = await db_session.scalars(
        select(Chunk.section_number).where(
            Chunk.tsv.op("@@")(func.websearch_to_tsquery("english", "gadget"))
        )
    )
    assert list(hits) == ["2"]
    act = await db_session.get(Act, document.act_id)
    assert act is not None
    assert act.source_file == "TST.pdf"


async def test_embeds_in_batches(
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    storage: DocumentStorage,
    settings: Settings,
) -> None:
    doc_id = await new_document(db_session, storage)
    embedder = FakeEmbedder()
    small_batches = settings.model_copy(update={"embedding_batch_size": 4})

    await make_pipeline(
        session_factory, storage, small_batches, FakeReader(FAKE_ACT_PAGES), embedder
    ).run(doc_id)

    assert [len(batch) for batch in embedder.calls] == [4, 2]


# ---------------------------------------------------------------- replace on re-upload
async def test_reupload_replaces_previous_version_of_same_act_only(
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    storage: DocumentStorage,
    settings: Settings,
) -> None:
    other_act_doc = await new_document(db_session, storage, act_code="OTHER", sha="c")
    v1 = await new_document(db_session, storage, sha="a")
    reader = FakeReader(FAKE_ACT_PAGES)
    for doc_id in (other_act_doc, v1):
        await make_pipeline(session_factory, storage, settings, reader).run(doc_id)

    v2 = await new_document(db_session, storage, sha="b")
    v2_pages = [PageText(1, "1. Placeholder only rule.—Version two body.")]
    await make_pipeline(session_factory, storage, settings, FakeReader(v2_pages)).run(v2)

    assert await reload(db_session, v1) is None  # old version removed ...
    assert not storage.path_for(v1).exists()  # ... with its file
    tst_chunks = list(
        await db_session.scalars(
            select(Chunk.text).join(Act, Act.id == Chunk.act_id).where(Act.short_code == "TST")
        )
    )
    assert tst_chunks == ["Version two body."]
    other = await reload(db_session, other_act_doc)
    assert other is not None
    assert other.chunks_count == 6  # a different act is untouched


async def test_in_flight_upload_of_same_act_is_not_deleted(
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    storage: DocumentStorage,
    settings: Settings,
) -> None:
    pending = await new_document(db_session, storage, sha="a")
    finished = await new_document(db_session, storage, sha="b")

    await make_pipeline(session_factory, storage, settings, FakeReader(FAKE_ACT_PAGES)).run(
        finished
    )

    still_pending = await reload(db_session, pending)
    assert still_pending is not None
    assert still_pending.status == DocumentStatus.PENDING


async def test_rerun_of_ready_document_is_skipped(
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    storage: DocumentStorage,
    settings: Settings,
) -> None:
    doc_id = await new_document(db_session, storage)
    reader = FakeReader(FAKE_ACT_PAGES)
    pipeline = make_pipeline(session_factory, storage, settings, reader)

    await pipeline.run(doc_id)
    await pipeline.run(doc_id)

    assert reader.calls == 1
    assert await db_session.scalar(select(func.count()).select_from(Chunk)) == 6


# ---------------------------------------------------------------- failures
@pytest.mark.parametrize(
    ("reader", "expected_error"),
    [
        (FakeReader(IngestionError("The PDF is password-protected.")), "password-protected"),
        (FakeReader(RuntimeError("boom")), UNEXPECTED_ERROR),
        (FakeReader([PageText(1, "A preamble with no numbered sections.")]), "No sections"),
    ],
)
async def test_failures_mark_document_failed(  # noqa: PLR0917  # parametrized fixtures
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    storage: DocumentStorage,
    settings: Settings,
    reader: FakeReader,
    expected_error: str,
) -> None:
    doc_id = await new_document(db_session, storage)

    await make_pipeline(session_factory, storage, settings, reader).run(doc_id)

    document = await reload(db_session, doc_id)
    assert document is not None
    assert document.status == DocumentStatus.FAILED
    assert document.error is not None
    assert expected_error in document.error
    assert "boom" not in document.error  # internal details stay in the logs
    assert await db_session.scalar(select(func.count()).select_from(Chunk)) == 0


async def test_missing_file_fails_cleanly(
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    storage: DocumentStorage,
    settings: Settings,
) -> None:
    doc_id = await new_document(db_session, storage)
    storage.path_for(doc_id).unlink()

    await make_pipeline(session_factory, storage, settings, FakeReader(FAKE_ACT_PAGES)).run(doc_id)

    document = await reload(db_session, doc_id)
    assert document is not None
    assert document.error is not None
    assert "missing" in document.error


async def test_wrong_embedding_size_fails(
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    storage: DocumentStorage,
    settings: Settings,
) -> None:
    class ShortVectors(FakeEmbedder):
        def embed(self, texts: object) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]  # type: ignore[attr-defined]

    doc_id = await new_document(db_session, storage)

    await make_pipeline(
        session_factory, storage, settings, FakeReader(FAKE_ACT_PAGES), ShortVectors()
    ).run(doc_id)

    document = await reload(db_session, doc_id)
    assert document is not None
    assert document.status == DocumentStatus.FAILED


async def test_unknown_document_is_ignored(
    session_factory: async_sessionmaker[AsyncSession], storage: DocumentStorage, settings: Settings
) -> None:
    reader = FakeReader(FAKE_ACT_PAGES)

    await make_pipeline(session_factory, storage, settings, reader).run(uuid.uuid4())

    assert reader.calls == 0
