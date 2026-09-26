import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.api.deps import AdminUserDep
from app.core.config import Settings
from app.core.security import create_token_pair
from app.db.models import User, UserRole
from tests.conftest import FakeUnitOfWork, InMemoryUserRepository

EMAIL = "Reader@Example.com"
PASSWORD = "s3cure-passphrase"


async def register(client: httpx.AsyncClient, email: str = EMAIL) -> httpx.Response:
    return await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})


async def login(client: httpx.AsyncClient, email: str = EMAIL) -> dict[str, Any]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


# ---------------------------------------------------------------- register
async def test_register_creates_user_with_normalized_email(
    client: httpx.AsyncClient, user_store: InMemoryUserRepository, uow: FakeUnitOfWork
) -> None:
    response = await register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "reader@example.com"
    assert body["role"] == "user"
    assert "password" not in response.text
    stored = next(iter(user_store.users.values()))
    assert stored.hashed_password.startswith("$2b$")
    assert uow.commits == 1


async def test_register_duplicate_email_conflicts(client: httpx.AsyncClient) -> None:
    await register(client)

    assert_error(await register(client, email="READER@example.com"), 409, "conflict")


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"email": "not-an-email", "password": PASSWORD}, "email"),
        ({"email": EMAIL, "password": "short"}, "password"),
        ({"email": EMAIL, "password": "é" * 37}, "password"),  # 74 bytes > bcrypt's 72
        ({"email": EMAIL}, "password"),
    ],
)
async def test_register_validation(
    client: httpx.AsyncClient, payload: dict[str, str], field: str
) -> None:
    response = await client.post("/api/v1/auth/register", json=payload)

    assert_error(response, 422, "validation_error")
    assert response.json()["error"]["details"][0]["loc"] == ["body", field]


# ---------------------------------------------------------------- login
async def test_login_returns_token_pair(client: httpx.AsyncClient, settings: Settings) -> None:
    await register(client)

    tokens = await login(client, email="reader@EXAMPLE.com")

    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == settings.access_token_expire_minutes * 60
    assert tokens["access_token"] != tokens["refresh_token"]


@pytest.mark.parametrize(
    ("email", "password"), [(EMAIL, "wrong-password"), ("nobody@example.com", PASSWORD)]
)
async def test_login_failure_is_generic(
    client: httpx.AsyncClient, email: str, password: str
) -> None:
    await register(client)

    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})

    assert_error(response, 401, "unauthorized")
    assert response.json()["error"]["message"] == "Invalid email or password."
    assert response.headers["WWW-Authenticate"] == "Bearer"


# ---------------------------------------------------------------- me
async def test_me_returns_current_user(client: httpx.AsyncClient) -> None:
    await register(client)
    tokens = await login(client)

    response = await client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"]))

    assert response.status_code == 200
    assert response.json()["email"] == "reader@example.com"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
    ],
)
async def test_me_rejects_missing_or_bad_credentials(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    assert_error(await client.get("/api/v1/auth/me", headers=headers), 401, "unauthorized")


async def test_me_rejects_refresh_token(client: httpx.AsyncClient) -> None:
    await register(client)
    tokens = await login(client)

    response = await client.get("/api/v1/auth/me", headers=bearer(tokens["refresh_token"]))

    assert_error(response, 401, "unauthorized")


async def test_token_for_deleted_user_rejected(
    client: httpx.AsyncClient, user_store: InMemoryUserRepository
) -> None:
    await register(client)
    tokens = await login(client)
    user_store.users.clear()

    response = await client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"]))

    assert_error(response, 401, "unauthorized")


async def test_token_with_non_uuid_subject_rejected(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    token = create_token_pair("not-a-uuid", settings).access_token

    response = await client.get("/api/v1/auth/me", headers=bearer(token))

    assert_error(response, 401, "unauthorized")


# ---------------------------------------------------------------- refresh
async def test_refresh_issues_working_tokens(client: httpx.AsyncClient) -> None:
    await register(client)
    tokens = await login(client)

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert response.status_code == 200
    new_access = response.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers=bearer(new_access))
    assert me.status_code == 200


async def test_refresh_rejects_access_token(client: httpx.AsyncClient) -> None:
    await register(client)
    tokens = await login(client)

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )

    assert_error(response, 401, "unauthorized")


# ---------------------------------------------------------------- admin guard
@pytest.fixture
def admin_route(app: FastAPI) -> None:
    async def admin_only(user: AdminUserDep) -> dict[str, str]:
        return {"email": user.email}

    app.add_api_route("/_test/admin", admin_only)


def _add_user(store: InMemoryUserRepository, role: UserRole) -> User:
    user = User(id=uuid.uuid4(), email=f"{role}@example.com", hashed_password="x", role=role)
    store.users[user.id] = user
    return user


@pytest.mark.usefixtures("admin_route")
async def test_admin_route_allows_admin(
    client: httpx.AsyncClient, user_store: InMemoryUserRepository, settings: Settings
) -> None:
    admin = _add_user(user_store, UserRole.ADMIN)
    token = create_token_pair(str(admin.id), settings).access_token

    response = await client.get("/_test/admin", headers=bearer(token))

    assert response.status_code == 200
    assert response.json() == {"email": "admin@example.com"}


@pytest.mark.usefixtures("admin_route")
async def test_admin_route_forbids_regular_user(
    client: httpx.AsyncClient, user_store: InMemoryUserRepository, settings: Settings
) -> None:
    user = _add_user(user_store, UserRole.USER)
    token = create_token_pair(str(user.id), settings).access_token

    assert_error(await client.get("/_test/admin", headers=bearer(token)), 403, "forbidden")


@pytest.mark.usefixtures("admin_route")
async def test_admin_route_requires_authentication(client: httpx.AsyncClient) -> None:
    assert_error(await client.get("/_test/admin"), 401, "unauthorized")
