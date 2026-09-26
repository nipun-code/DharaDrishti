"""Registration, login, token refresh and admin bootstrap."""

import logging
import uuid
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    TokenPair,
    TokenType,
    burn_password_check,
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models import User, UserRole

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Invalid email or password."


class UserStore(Protocol):
    async def get(self, id_: uuid.UUID) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
    async def add(self, obj: User) -> User: ...


class UnitOfWork(Protocol):
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class AuthService:
    def __init__(self, users: UserStore, uow: UnitOfWork, settings: Settings) -> None:
        self._users = users
        self._uow = uow
        self._settings = settings

    async def register(self, email: str, password: str, role: UserRole = UserRole.USER) -> User:
        """Create a user. `email` must be normalized; `password` already policy-validated."""
        if await self._users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists.")
        user = User(
            email=email,
            hashed_password=await hash_password(password, self._settings.bcrypt_rounds),
            role=role,
        )
        await self._users.add(user)
        try:
            await self._uow.commit()
        except IntegrityError as exc:  # lost a race with a concurrent registration
            await self._uow.rollback()
            raise ConflictError("An account with this email already exists.") from exc
        logger.info("user_registered", extra={"user_id": str(user.id), "role": role.value})
        return user

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self._users.get_by_email(email)
        if user is None:
            await burn_password_check(password, self._settings.bcrypt_rounds)
            raise UnauthorizedError(INVALID_CREDENTIALS)
        if not await verify_password(password, user.hashed_password):
            raise UnauthorizedError(INVALID_CREDENTIALS)
        logger.info("user_logged_in", extra={"user_id": str(user.id)})
        return create_token_pair(str(user.id), self._settings)

    async def refresh(self, refresh_token: str) -> TokenPair:
        user = await self._user_from_token(refresh_token, TokenType.REFRESH)
        return create_token_pair(str(user.id), self._settings)

    async def authenticate_access_token(self, access_token: str) -> User:
        return await self._user_from_token(access_token, TokenType.ACCESS)

    async def ensure_admin(self, email: str, password: str) -> tuple[User, bool]:
        """Create an admin, or promote an existing user (password unchanged).

        Returns (user, created).
        """
        existing = await self._users.get_by_email(email)
        if existing is None:
            return await self.register(email, password, role=UserRole.ADMIN), True
        if existing.role != UserRole.ADMIN:
            existing.role = UserRole.ADMIN
            await self._uow.commit()
            logger.info("user_promoted_to_admin", extra={"user_id": str(existing.id)})
        return existing, False

    async def _user_from_token(self, token: str, token_type: TokenType) -> User:
        subject = decode_token(token, token_type, self._settings)
        try:
            user_id = uuid.UUID(subject)
        except ValueError as exc:
            raise UnauthorizedError("Invalid token.") from exc
        user = await self._users.get(user_id)
        if user is None:
            raise UnauthorizedError("Invalid token.")
        return user
