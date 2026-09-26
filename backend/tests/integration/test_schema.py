"""The migration produces exactly the schema the ORM models describe, with the search indexes."""

from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models  # noqa: F401  # register tables
from app.db.base import Base

pytestmark = pytest.mark.integration


def _diff(sync_conn: Connection) -> list[Any]:
    ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
    return list(compare_metadata(ctx, Base.metadata))


async def test_migration_matches_models(db_session: AsyncSession) -> None:
    conn = await db_session.connection()

    diff = await conn.run_sync(_diff)

    assert diff == []


async def test_vector_extension_installed(db_session: AsyncSession) -> None:
    version = await db_session.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )

    assert version is not None


@pytest.mark.parametrize(
    ("index", "fragment"),
    [
        ("ix_chunks_tsv", "USING gin (tsv)"),
        ("ix_chunks_embedding_hnsw", "USING hnsw (embedding vector_cosine_ops)"),
        ("ix_chunks_act_id_section_number", "USING btree (act_id, section_number)"),
    ],
)
async def test_chunk_indexes(db_session: AsyncSession, index: str, fragment: str) -> None:
    definition = await db_session.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"), {"name": index}
    )

    assert definition is not None
    assert fragment in definition


async def test_tsv_is_generated_column(db_session: AsyncSession) -> None:
    generated = await db_session.scalar(
        text(
            "SELECT is_generated FROM information_schema.columns "
            "WHERE table_name = 'chunks' AND column_name = 'tsv'"
        )
    )

    assert generated == "ALWAYS"
