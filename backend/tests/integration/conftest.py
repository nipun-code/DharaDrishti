"""Fixtures for tests against a real PostgreSQL (+pgvector).

A dedicated `<DATABASE_URL db>_test` database is created and migrated once per session
(upgrade -> downgrade -> upgrade, which also exercises the downgrade path). Each test runs inside
an outer transaction that is rolled back, so tests never see each other's data even though the
services under test call commit() (commits become SAVEPOINT releases).

Everything here is skipped when PostgreSQL is unreachable (e.g. a plain local run).
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = database_url
    cfg.attributes["configure_logger"] = False
    return cfg


async def _ensure_database(admin_url: str, db_name: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await engine.dispose()


def _is_unreachable(exc: BaseException) -> bool:
    """True only for "nothing is listening" errors. Anything else (bad password, missing
    privileges) is a misconfiguration and must fail loudly rather than silently skip."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, (OSError, TimeoutError)):
            return True
        current = current.__cause__ or current.__context__
    return False


@pytest.fixture(scope="session")
def test_database_url() -> str:
    get_settings.cache_clear()
    url = make_url(get_settings().database_url.get_secret_value())
    test_url = url.set(database=f"{url.database}_test")
    # render_as_string: str(URL) masks the password as "***".
    admin_url = url.render_as_string(hide_password=False)
    try:
        asyncio.run(asyncio.wait_for(_ensure_database(admin_url, test_url.database or ""), 5))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        if not _is_unreachable(exc):
            raise
        pytest.skip(f"PostgreSQL not reachable ({type(exc).__name__}); run via docker compose")

    rendered = test_url.render_as_string(hide_password=False)
    cfg = _alembic_config(rendered)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return rendered


@pytest.fixture
async def session_factory(
    test_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions bound to one connection inside an outer transaction that is rolled back at the
    end; their commit() calls only release savepoints. Use for code that opens its own
    sessions (e.g. the ingestion pipeline)."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        try:
            yield async_sessionmaker(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
        finally:
            await outer.rollback()
    await engine.dispose()


@pytest.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
