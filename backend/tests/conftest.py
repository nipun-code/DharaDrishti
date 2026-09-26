import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

# Must be set before app modules that call get_settings() at import time (e.g. the ARQ worker).
# Values here are local test placeholders, not real credentials.
# Port 1: nothing listens there, so DB integration tests skip unless DATABASE_URL is set for real.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:1/test")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-secret-key-0123456789abcdef")

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.api.deps import get_db_session, get_health_service, get_user_repository
from app.core.config import Settings
from app.db.models import User
from app.main import create_app
from app.services.health import HealthService

TEST_JWT_SECRET = "test-only-jwt-secret-key-0123456789abcdef"


class FakeProbe:
    """Test double for a dependency probe."""

    def __init__(self, name: str, *, error: BaseException | None = None, delay: float = 0) -> None:
        self.name = name
        self._error = error
        self._delay = delay

    async def ping(self) -> None:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error


class InMemoryUserRepository:
    """Implements the UserStore protocol without a database."""

    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

    async def get(self, id_: uuid.UUID) -> User | None:
        return self.users.get(id_)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.users.values() if u.email == email), None)

    async def add(self, obj: User) -> User:
        obj.id = obj.id or uuid.uuid4()
        obj.created_at = obj.created_at or datetime.now(UTC)
        self.users[obj.id] = obj
        return obj


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost:1/test"),
        redis_url="redis://localhost:1/0",
        environment="test",
        health_check_timeout_seconds=0.2,
        jwt_secret_key=SecretStr(TEST_JWT_SECRET),
        bcrypt_rounds=4,  # minimum cost: keeps the suite fast
        _env_file=None,
    )


@pytest.fixture
def user_store() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def app(settings: Settings, user_store: InMemoryUserRepository, uow: FakeUnitOfWork) -> FastAPI:
    """App wired to in-memory fakes, so unit tests need no PostgreSQL."""
    application = create_app(settings)
    application.dependency_overrides[get_db_session] = lambda: uow
    application.dependency_overrides[get_user_repository] = lambda: user_store
    return application


def override_probes(app: FastAPI, *probes: FakeProbe, timeout: float = 0.2) -> None:
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        probes=list(probes), timeout_seconds=timeout
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
