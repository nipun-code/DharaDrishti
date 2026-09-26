from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.main import create_app


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Run the app's real lifespan and yield a client bound to it."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_lifespan_creates_resources(settings: Settings) -> None:
    app = create_app(settings)

    async with running(app) as client:
        assert isinstance(app.state.engine, AsyncEngine)
        assert isinstance(app.state.redis, Redis)
        assert (await client.get("/health/live")).status_code == 200


async def test_ready_reports_unavailable_when_infra_unreachable(settings: Settings) -> None:
    # settings point at port 1, where nothing listens: exercises the real probes end to end.
    async with running(create_app(settings)) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    checks = response.json()["checks"]
    assert checks["database"]["status"] == "error"
    assert checks["redis"]["status"] == "error"


async def test_docs_disabled_in_production(settings: Settings) -> None:
    prod = settings.model_copy(update={"environment": "production"})

    async with running(create_app(prod)) as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 200


async def test_docs_enabled_outside_production(settings: Settings) -> None:
    async with running(create_app(settings)) as client:
        assert (await client.get("/docs")).status_code == 200


def test_settings_hide_database_secret() -> None:
    s = Settings(
        database_url=SecretStr("postgresql+asyncpg://u:supersecret@db/x"),
        _env_file=None,
    )

    assert "supersecret" not in repr(s)
    assert s.database_url.get_secret_value().endswith("@db/x")
    assert not s.is_production


def test_get_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("HEALTH_CHECK_TIMEOUT_SECONDS", "7.5")
    get_settings.cache_clear()
    try:
        loaded = get_settings()
        assert loaded.is_production
        assert loaded.health_check_timeout_seconds == 7.5
        assert get_settings() is loaded
    finally:
        get_settings.cache_clear()


def test_metadata_uses_naming_convention() -> None:
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"
