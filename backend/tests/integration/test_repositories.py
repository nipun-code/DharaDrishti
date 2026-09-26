"""Repositories against real PostgreSQL. Fixture rows are synthetic test data, not legal content."""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Act,
    ActStatus,
    Chunk,
    Document,
    DocumentStatus,
    EvalRun,
    Feedback,
    QueryLog,
    SectionMapping,
    User,
    UserRole,
)
from app.db.models.types import EMBEDDING_DIM
from app.repositories.acts import ActRepository
from app.repositories.chunks import ChunkRepository
from app.repositories.documents import DocumentRepository
from app.repositories.eval_runs import EvalRunRepository
from app.repositories.feedback import FeedbackRepository
from app.repositories.query_logs import QueryLogRepository
from app.repositories.section_mappings import SectionMappingRepository
from app.repositories.users import UserRepository

pytestmark = pytest.mark.integration


def unit_vector(hot: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[hot] = 1.0
    return vec


async def make_user(session: AsyncSession, email: str = "user@example.com") -> User:
    return await UserRepository(session).add(User(email=email, hashed_password="x"))


async def make_act(session: AsyncSession, code: str = "TESTACT") -> Act:
    return await ActRepository(session).add(Act(short_code=code, full_name="Test Act", year=2000))


async def make_document(session: AsyncSession, act: Act, sha: str = "a" * 64) -> Document:
    return await DocumentRepository(session).add(
        Document(act_id=act.id, filename="test.pdf", sha256=sha)
    )


def make_chunk(act: Act, doc: Document, section: str, body: str, hot: int) -> Chunk:
    return Chunk(
        act_id=act.id,
        document_id=doc.id,
        section_number=section,
        section_title=f"Heading {section}",
        text=body,
        token_count=len(body.split()),
        embedding=unit_vector(hot),
    )


# ---------------------------------------------------------------- users
async def test_user_defaults_and_lookup(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    user = await make_user(db_session)

    assert isinstance(user.id, uuid.UUID)
    assert user.role == UserRole.USER
    assert user.created_at is not None
    assert await repo.get_by_email("user@example.com") is user
    assert await repo.get(user.id) is user
    assert await repo.get_by_email("missing@example.com") is None


async def test_user_email_unique(db_session: AsyncSession) -> None:
    await make_user(db_session)

    with pytest.raises(IntegrityError):
        await make_user(db_session)


async def test_role_check_constraint(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_users_user_role"):
        await db_session.execute(
            text("INSERT INTO users (email, hashed_password, role) VALUES ('r@x.io', 'x', 'root')")
        )


async def test_invalid_enum_rejected_before_sql(db_session: AsyncSession) -> None:
    with pytest.raises(StatementError):
        await make_user_with_role(db_session, "superuser")


async def make_user_with_role(session: AsyncSession, role: str) -> None:
    await UserRepository(session).add(User(email="e@example.com", hashed_password="x", role=role))


# ---------------------------------------------------------------- acts & documents
async def test_act_lookup_and_listing(db_session: AsyncSession) -> None:
    repo = ActRepository(db_session)
    await make_act(db_session, "ZZZ")
    act = await make_act(db_session, "AAA")

    assert act.status == ActStatus.IN_FORCE
    assert await repo.get_by_short_code("AAA") is act
    assert [a.short_code for a in await repo.list_all()] == ["AAA", "ZZZ"]


async def test_document_defaults_dedup_and_update(db_session: AsyncSession) -> None:
    repo = DocumentRepository(db_session)
    act = await make_act(db_session)
    doc = await make_document(db_session, act)
    first_updated_at = doc.updated_at

    assert doc.status == DocumentStatus.PENDING
    assert doc.chunks_count == 0
    assert await repo.get_by_sha256("a" * 64) is doc
    assert await repo.list_recent() == [doc]

    doc.status = DocumentStatus.READY
    await db_session.flush()
    assert doc.updated_at > first_updated_at

    with pytest.raises(IntegrityError):
        await make_document(db_session, act)  # same sha256


# ---------------------------------------------------------------- chunks
async def test_chunks_fulltext_and_vector_search(db_session: AsyncSession) -> None:
    act = await make_act(db_session)
    doc = await make_document(db_session, act)
    repo = ChunkRepository(db_session)
    await repo.add_all(
        [
            make_chunk(act, doc, "1", "Alpha provisions about widgets and gadgets.", hot=0),
            make_chunk(act, doc, "2", "Beta provisions about sprockets.", hot=1),
            make_chunk(act, doc, "2", "Beta continued, second piece.", hot=2),
        ]
    )

    # tsvector is generated by PostgreSQL from section_title + text.
    fts = select(Chunk.section_number).where(
        Chunk.tsv.op("@@")(func.websearch_to_tsquery("english", "widgets"))
    )
    assert list(await db_session.scalars(fts)) == ["1"]
    title_hit = select(func.count()).where(
        Chunk.tsv.op("@@")(func.websearch_to_tsquery("english", "heading"))
    )
    assert await db_session.scalar(title_hit) == 3

    nearest = select(Chunk.text).order_by(Chunk.embedding.cosine_distance(unit_vector(1))).limit(1)
    assert await db_session.scalar(nearest) == "Beta provisions about sprockets."

    section = await repo.list_for_section(act.id, "2")
    assert [c.text for c in section] == [
        "Beta provisions about sprockets.",
        "Beta continued, second piece.",
    ]


async def test_deleting_document_cascades_to_chunks(db_session: AsyncSession) -> None:
    act = await make_act(db_session)
    doc = await make_document(db_session, act)
    await ChunkRepository(db_session).add(make_chunk(act, doc, "1", "Some text.", hot=0))

    await DocumentRepository(db_session).delete(doc)
    db_session.expunge_all()

    assert await db_session.scalar(select(func.count()).select_from(Chunk)) == 0


# ---------------------------------------------------------------- mappings, logs, feedback, eval
async def test_section_mapping_lookup(db_session: AsyncSession) -> None:
    repo = SectionMappingRepository(db_session)
    await repo.add_all(
        [
            SectionMapping(from_act="OLD", from_section="10", to_act="NEW", to_section="20"),
            SectionMapping(from_act="OLD", from_section="10", to_act="NEW", to_section="21"),
            SectionMapping(from_act="OLD", from_section="11", to_act="NEW", to_section="22"),
        ]
    )

    found = await repo.list_from("OLD", "10")

    assert [m.to_section for m in found] == ["20", "21"]


async def test_query_log_defaults_and_feedback(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    log = await QueryLogRepository(db_session).add(QueryLog(user_id=user.id, query="test?"))

    assert log.retrieved_chunk_ids == []
    assert log.guardrail_flags == []
    assert log.refused is False
    assert log.cache_hit is False

    feedback_repo = FeedbackRepository(db_session)
    vote = await feedback_repo.add(Feedback(query_log_id=log.id, user_id=user.id, rating=1))
    assert await feedback_repo.get_for_user(log.id, user.id) is vote

    with pytest.raises(IntegrityError):  # one vote per user per answer
        await feedback_repo.add(Feedback(query_log_id=log.id, user_id=user.id, rating=-1))


async def test_feedback_rating_constraint(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    log = await QueryLogRepository(db_session).add(QueryLog(user_id=user.id, query="q"))

    with pytest.raises(IntegrityError, match="rating_is_plus_or_minus_one"):
        await FeedbackRepository(db_session).add(
            Feedback(query_log_id=log.id, user_id=user.id, rating=5)
        )


async def test_eval_runs_listed_newest_first(db_session: AsyncSession) -> None:
    repo = EvalRunRepository(db_session)
    await repo.add(EvalRun(config={"modes": ["vector"]}))
    await db_session.execute(text("SELECT pg_sleep(0.01)"))
    await db_session.commit()  # new transaction -> later now()
    latest = await repo.add(EvalRun(config={"modes": ["hybrid"]}, metrics={"mrr": 0.5}))

    runs = await repo.list_recent()

    assert runs[0] is latest
    assert len(runs) == 2


async def test_raw_sql_insert_gets_uuid_from_database(db_session: AsyncSession) -> None:
    new_id = await db_session.scalar(
        text("INSERT INTO eval_runs (config) VALUES ('{}'::jsonb) RETURNING id")
    )

    assert isinstance(new_id, uuid.UUID)


async def test_role_values_stored_as_plain_strings(db_session: AsyncSession) -> None:
    await UserRepository(db_session).add(
        User(email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
    )

    raw = await db_session.scalar(text("SELECT role FROM users WHERE email = 'admin@example.com'"))

    assert raw == "admin"
