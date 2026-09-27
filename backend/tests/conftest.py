import asyncio
import os
import re
import uuid
import zlib
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

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
from app.db.models.types import EMBEDDING_DIM
from app.main import create_app
from app.services.health import HealthService
from app.services.llm.base import LLMRequest, LLMResponse

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


class FakeEmbedder:
    """Deterministic stand-in for the sentence-transformers model (no downloads in tests)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            vector = [0.0] * EMBEDDING_DIM
            vector[zlib.crc32(text.encode()) % EMBEDDING_DIM] = 1.0
            vectors.append(vector)
        return vectors

    def count_tokens(self, text: str) -> int:
        return len(text.split())


def unit_vector(*dims: int) -> list[float]:
    """Normalized vector with equal weight on the given dimensions."""
    vector = [0.0] * EMBEDDING_DIM
    for dim in dims:
        vector[dim] = 1.0 / len(dims) ** 0.5
    return vector


class FakeQueryEmbedder:
    """Query embedder whose vectors are chosen by the test (default: dimension 383)."""

    def __init__(self, vectors: dict[str, list[float]] | None = None) -> None:
        self.vectors = vectors or {}
        self.calls: list[list[str]] = []

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.vectors.get(text, unit_vector(EMBEDDING_DIM - 1)) for text in texts]


class FakeReranker:
    """Scores a passage by how many query words it contains (deterministic, no model)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, len(passages)))
        words = {w.strip("?.,").lower() for w in query.split()}
        return [
            min(1.0, sum(w in passage.lower() for w in words) / max(len(words), 1))
            for passage in passages
        ]


class FakeJobQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.fail = fail

    async def enqueue_ingestion(self, document_id: uuid.UUID) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.enqueued.append(document_id)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost:1/test"),
        redis_url="redis://localhost:1/0",
        environment="test",
        health_check_timeout_seconds=0.2,
        jwt_secret_key=SecretStr(TEST_JWT_SECRET),
        bcrypt_rounds=4,  # minimum cost: keeps the suite fast
        upload_dir=tmp_path / "uploads",
        max_upload_mb=1,
        data_dir=tmp_path / "data",
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


# ---------------------------------------------------------------- Phase 4 fakes
_WORD_RE = re.compile(r"\S+\s*")


class FakeLLM:
    """Scripted LLM client. Replies are chosen by LLMRequest.purpose; a list of replies is
    consumed in order (the last one repeats). An Exception reply is raised."""

    DEFAULTS: ClassVar[dict[str, str]] = {
        "topic": '{"category": "legal", "reason": "law"}',
        "rewrite": '{"queries": ["legal phrasing of the question"]}',
        "answer": "The placeholder rule says widgets need registration [1].",
        "answer_retry": "Strictly, the placeholder rule requires registration [1].",
        "faithfulness": '{"faithful": true, "unsupported_claims": []}',
    }

    def __init__(self, **script: str | Exception | list[str | Exception]) -> None:
        merged: dict[str, Any] = {**self.DEFAULTS, **script}
        self.script = {k: list(v) if isinstance(v, list) else [v] for k, v in merged.items()}
        self.requests: list[LLMRequest] = []

    @property
    def purposes(self) -> list[str]:
        return [r.purpose for r in self.requests]

    def _reply(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        replies = self.script[request.purpose]
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(reply, "fake", "fake-model", 10, len(reply.split()))

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return self._reply(request)

    async def stream(self, request: LLMRequest) -> AsyncIterator[str | LLMResponse]:
        response = self._reply(request)
        for piece in _WORD_RE.findall(response.text):
            yield piece
        yield response


class FakeRedis:
    """The handful of async Redis commands the app uses, in memory (TTL ignored)."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.expiries: dict[str, int] = {}

    async def get(self, key: str) -> Any:
        return self.data.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex:
            self.expiries[key] = ex
        return True

    async def incr(self, key: str) -> int:
        return await self.incrby(key, 1)

    async def incrby(self, key: str, amount: int) -> int:
        self.data[key] = int(self.data.get(key) or 0) + amount
        return int(self.data[key])

    async def expire(self, key: str, seconds: int) -> bool:
        self.expiries[key] = seconds
        return True


class MemoryQueryStore:
    def __init__(self, mapped: set[str] | None = None) -> None:
        self.entries: list[Any] = []
        self.mapped = mapped or set()

    async def log(self, entry: Any) -> uuid.UUID:
        self.entries.append(entry)
        return uuid.uuid4()

    async def mapped_sections(self, numbers: Any) -> set[str]:
        return self.mapped & set(numbers)
