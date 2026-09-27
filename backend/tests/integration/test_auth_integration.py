"""Auth end to end through the API and the CLI, against real PostgreSQL."""

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_db_session, get_rate_limiter
from app.cli import create_admin
from app.core.config import Settings
from app.db.models import User, UserRole
from app.main import create_app
from app.repositories.users import UserRepository
from app.services.limits import RateLimiter
from tests.conftest import FakeRedis

pytestmark = pytest.mark.integration


@pytest.fixture
async def db_client(
    settings: Settings, db_session: AsyncSession
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    app.dependency_overrides[get_db_session] = lambda: db_session
    limiter = RateLimiter(FakeRedis())  # type: ignore[arg-type]
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_register_login_me_refresh(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creds = {"email": "Flow@Example.com", "password": "integration-pass"}

    registered = await db_client.post("/api/v1/auth/register", json=creds)
    assert registered.status_code == 201
    stored = await UserRepository(db_session).get_by_email("flow@example.com")
    assert stored is not None
    assert stored.hashed_password != creds["password"]

    duplicate = await db_client.post("/api/v1/auth/register", json=creds)
    assert duplicate.status_code == 409

    tokens = (await db_client.post("/api/v1/auth/login", json=creds)).json()
    me = await db_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.json()["id"] == str(stored.id)

    refreshed = await db_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200


async def test_cli_create_admin_then_promote_is_idempotent(
    settings: Settings, test_database_url: str
) -> None:
    # create_admin opens its own engine and really commits, so clean up explicitly.
    db_settings = settings.model_copy(update={"database_url": SecretStr(test_database_url)})
    email = "cli-admin@example.com"
    try:
        user, created = await create_admin(db_settings, email, "cli-admin-pass")
        assert created
        assert user.role == UserRole.ADMIN

        again, created_again = await create_admin(db_settings, email, "ignored-pass")
        assert not created_again
        assert again.id == user.id
    finally:
        engine = create_async_engine(
            make_url(test_database_url).render_as_string(hide_password=False),
            poolclass=NullPool,
        )
        async with engine.begin() as conn:
            await conn.execute(delete(User).where(User.email == email))
        await engine.dispose()
