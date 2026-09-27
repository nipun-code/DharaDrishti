"""FastAPI dependency providers. Infrastructure objects live on app.state (created in lifespan)."""

from collections.abc import AsyncIterator
from typing import Annotated, cast

from arq.connections import ArqRedis
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.db.models import User, UserRole
from app.repositories.health import DatabaseProbe, RedisProbe
from app.repositories.users import UserRepository
from app.services.auth import AuthService
from app.services.documents import DocumentService
from app.services.health import HealthService
from app.services.ingestion.storage import DocumentStorage
from app.workers.queue import ArqJobQueue, JobQueue


def get_settings_dep(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.engine)


def get_redis(request: Request) -> Redis:
    return cast(Redis, request.app.state.redis)


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
RedisDep = Annotated[Redis, Depends(get_redis)]


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Services commit explicitly; anything uncommitted is rolled back
    when the session closes."""
    factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    async with factory() as session:
        yield session


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


# ---------------------------------------------------------------- health
def get_health_service(settings: SettingsDep, engine: EngineDep, redis: RedisDep) -> HealthService:
    return HealthService(
        probes=[DatabaseProbe(engine), RedisProbe(redis)],
        timeout_seconds=settings.health_check_timeout_seconds,
    )


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]


# ---------------------------------------------------------------- auth
def get_user_repository(session: DbSessionDep) -> UserRepository:
    return UserRepository(session)


def get_auth_service(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    session: DbSessionDep,
    settings: SettingsDep,
) -> AuthService:
    return AuthService(users=users, uow=session, settings=settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

# auto_error=False so a missing/malformed header yields our 401 envelope instead of FastAPI's 403.
_bearer = HTTPBearer(auto_error=False, description="Access token from POST /api/v1/auth/login")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    auth: AuthServiceDep,
) -> User:
    if credentials is None:
        raise UnauthorizedError
    return await auth.authenticate_access_token(credentials.credentials)


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUserDep) -> User:
    """Use as `Depends(require_admin)` on admin-only routes (ingestion, eval, analytics)."""
    if user.role != UserRole.ADMIN:
        raise ForbiddenError
    return user


AdminUserDep = Annotated[User, Depends(require_admin)]


# ---------------------------------------------------------------- documents
def get_job_queue(request: Request) -> JobQueue:
    return ArqJobQueue(cast(ArqRedis, request.app.state.arq))


def get_document_storage(settings: SettingsDep) -> DocumentStorage:
    return DocumentStorage(settings.upload_dir)


def get_document_service(
    session: DbSessionDep,
    storage: Annotated[DocumentStorage, Depends(get_document_storage)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
    settings: SettingsDep,
) -> DocumentService:
    return DocumentService(session=session, storage=storage, queue=queue, settings=settings)


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
