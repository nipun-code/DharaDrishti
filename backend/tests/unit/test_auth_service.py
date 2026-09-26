import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.exceptions import ConflictError
from app.core.security import verify_password
from app.db.models import UserRole
from app.services.auth import AuthService
from tests.conftest import FakeUnitOfWork, InMemoryUserRepository


@pytest.fixture
def service(
    user_store: InMemoryUserRepository, uow: FakeUnitOfWork, settings: Settings
) -> AuthService:
    return AuthService(users=user_store, uow=uow, settings=settings)


async def test_register_race_maps_integrity_error_to_conflict(
    service: AuthService, uow: FakeUnitOfWork
) -> None:
    async def failing_commit() -> None:
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    uow.commit = failing_commit  # type: ignore[method-assign]

    with pytest.raises(ConflictError):
        await service.register("race@example.com", "password123")
    assert uow.rollbacks == 1


async def test_ensure_admin_creates_new_admin(
    service: AuthService, user_store: InMemoryUserRepository
) -> None:
    user, created = await service.ensure_admin("root@example.com", "password123")

    assert created
    assert user.role == UserRole.ADMIN
    assert await verify_password("password123", user.hashed_password)
    assert list(user_store.users.values()) == [user]


async def test_ensure_admin_promotes_existing_user_without_changing_password(
    service: AuthService, uow: FakeUnitOfWork
) -> None:
    existing = await service.register("member@example.com", "original-pass")
    original_hash = existing.hashed_password

    user, created = await service.ensure_admin("member@example.com", "different-pass")

    assert not created
    assert user is existing
    assert user.role == UserRole.ADMIN
    assert user.hashed_password == original_hash
    assert uow.commits == 2


async def test_ensure_admin_is_idempotent(service: AuthService, uow: FakeUnitOfWork) -> None:
    await service.ensure_admin("root@example.com", "password123")
    commits = uow.commits

    _, created = await service.ensure_admin("root@example.com", "password123")

    assert not created
    assert uow.commits == commits  # nothing to change, nothing committed
