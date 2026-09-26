"""Readiness against real PostgreSQL + Redis (from DATABASE_URL / REDIS_URL).

Runs inside `docker compose exec api pytest` and in CI. Skipped when the services are unreachable
(e.g. a plain local run without Docker) so the unit suite still works standalone.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.db.redis import create_redis
from app.db.session import create_engine
from app.main import create_app
from app.repositories.health import DatabaseProbe, RedisProbe

pytestmark = pytest.mark.integration


async def _services_reachable(settings: Settings) -> bool:
    engine = create_engine(settings)
    redis = create_redis(settings)
    try:
        await DatabaseProbe(engine).ping()
        await RedisProbe(redis).ping()
    except Exception:  # noqa: BLE001
        return False
    else:
        return True
    finally:
        await redis.aclose()
        await engine.dispose()


@pytest.fixture
async def live_app() -> AsyncIterator[FastAPI]:
    get_settings.cache_clear()
    settings = get_settings()
    if not await _services_reachable(settings):
        pytest.skip("PostgreSQL/Redis not reachable; run via docker compose to include this test")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app
    get_settings.cache_clear()


async def test_ready_with_real_dependencies(live_app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=live_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"
