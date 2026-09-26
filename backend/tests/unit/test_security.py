from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    TokenType,
    _encode,
    burn_password_check,
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
)


async def test_hash_and_verify_roundtrip() -> None:
    hashed = await hash_password("correct horse", rounds=4)

    assert hashed.startswith("$2b$04$")
    assert await verify_password("correct horse", hashed)
    assert not await verify_password("wrong horse", hashed)


async def test_hashes_are_salted() -> None:
    assert await hash_password("same", rounds=4) != await hash_password("same", rounds=4)


async def test_verify_with_malformed_hash_is_false() -> None:
    assert not await verify_password("whatever", "not-a-bcrypt-hash")


async def test_burn_password_check_completes() -> None:
    await burn_password_check("anything", rounds=4)


def test_token_pair_roundtrip(settings: Settings) -> None:
    pair = create_token_pair("user-123", settings)

    assert decode_token(pair.access_token, TokenType.ACCESS, settings) == "user-123"
    assert decode_token(pair.refresh_token, TokenType.REFRESH, settings) == "user-123"
    assert pair.expires_in == settings.access_token_expire_minutes * 60


def test_token_type_is_enforced(settings: Settings) -> None:
    pair = create_token_pair("user-123", settings)

    with pytest.raises(UnauthorizedError, match="token type"):
        decode_token(pair.refresh_token, TokenType.ACCESS, settings)
    with pytest.raises(UnauthorizedError, match="token type"):
        decode_token(pair.access_token, TokenType.REFRESH, settings)


def test_expired_token_rejected(settings: Settings) -> None:
    token = _encode("user-123", TokenType.ACCESS, timedelta(seconds=-1), settings)

    with pytest.raises(UnauthorizedError, match="expired"):
        decode_token(token, TokenType.ACCESS, settings)


def test_token_signed_with_other_key_rejected(settings: Settings) -> None:
    other = settings.model_copy(update={"jwt_secret_key": SecretStr("x" * 40)})
    token = create_token_pair("user-123", other).access_token

    with pytest.raises(UnauthorizedError, match="Invalid token"):
        decode_token(token, TokenType.ACCESS, settings)


def test_tampered_token_rejected(settings: Settings) -> None:
    token = create_token_pair("user-123", settings).access_token
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}AA"

    with pytest.raises(UnauthorizedError):
        decode_token(tampered, TokenType.ACCESS, settings)


def test_token_missing_required_claims_rejected(settings: Settings) -> None:
    token = jwt.encode(
        {"sub": "user-123", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )

    with pytest.raises(UnauthorizedError):
        decode_token(token, TokenType.ACCESS, settings)


def test_alg_none_token_rejected(settings: Settings) -> None:
    now = datetime.now(UTC)
    claims = {"sub": "u", "type": "access", "iat": now, "exp": now + timedelta(minutes=5)}
    token = jwt.encode({**claims, "jti": "x"}, key=None, algorithm="none")

    with pytest.raises(UnauthorizedError):
        decode_token(token, TokenType.ACCESS, settings)


def test_short_jwt_secret_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(
            database_url=SecretStr("postgresql+asyncpg://u:p@h/d"),
            jwt_secret_key=SecretStr("too-short"),
            _env_file=None,
        )
