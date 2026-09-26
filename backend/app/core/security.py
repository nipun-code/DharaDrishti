"""Password hashing (bcrypt) and JWT access/refresh tokens."""

import asyncio
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache

import bcrypt
import jwt

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError

# bcrypt only looks at the first 72 bytes; longer inputs are rejected at the schema layer.
BCRYPT_MAX_PASSWORD_BYTES = 72


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int  # access token lifetime, seconds


# ---------------------------------------------------------------- passwords
def _hash_sync(password: str, rounds: int) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


def _verify_sync(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:  # malformed hash or over-long password
        return False


async def hash_password(password: str, rounds: int) -> str:
    """Hash off the event loop: bcrypt is deliberately CPU-expensive."""
    return await asyncio.to_thread(_hash_sync, password, rounds)


async def verify_password(password: str, hashed: str) -> bool:
    return await asyncio.to_thread(_verify_sync, password, hashed)


@lru_cache(maxsize=4)
def _dummy_hash_sync(rounds: int) -> str:
    return _hash_sync(secrets.token_urlsafe(16), rounds)


async def burn_password_check(password: str, rounds: int) -> None:
    """Spend the same time as a real check. Used when the account doesn't exist, so response
    timing does not reveal which emails are registered."""
    dummy = await asyncio.to_thread(_dummy_hash_sync, rounds)
    await verify_password(password, dummy)


# ---------------------------------------------------------------- tokens
def _encode(subject: str, token_type: TokenType, ttl: timedelta, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def create_token_pair(subject: str, settings: Settings) -> TokenPair:
    access_ttl = timedelta(minutes=settings.access_token_expire_minutes)
    refresh_ttl = timedelta(days=settings.refresh_token_expire_days)
    return TokenPair(
        access_token=_encode(subject, TokenType.ACCESS, access_ttl, settings),
        refresh_token=_encode(subject, TokenType.REFRESH, refresh_ttl, settings),
        expires_in=int(access_ttl.total_seconds()),
    )


def decode_token(token: str, expected_type: TokenType, settings: Settings) -> str:
    """Validate signature, expiry and token type; return the subject. Raises UnauthorizedError."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "type", "exp", "iat", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid token.") from exc

    if payload.get("type") != expected_type.value:
        raise UnauthorizedError("Invalid token type.")
    return str(payload["sub"])  # PyJWT already validated that "sub" is a string
