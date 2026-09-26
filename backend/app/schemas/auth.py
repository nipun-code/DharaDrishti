"""Auth request/response schemas."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from app.core.security import BCRYPT_MAX_PASSWORD_BYTES
from app.db.models.enums import UserRole

MIN_PASSWORD_LENGTH = 8


def normalize_email(value: str) -> str:
    return value.strip().lower()


def _check_password_bytes(value: str) -> str:
    if len(value.encode()) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes (UTF-8).")
    return value


Email = Annotated[EmailStr, AfterValidator(normalize_email)]
NewPassword = Annotated[
    str, Field(min_length=MIN_PASSWORD_LENGTH), AfterValidator(_check_password_bytes)
]


class RegisterRequest(BaseModel):
    email: Email
    password: NewPassword


class LoginRequest(BaseModel):
    email: Email
    # No length rules on login: never hint at password policy for an existing account.
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  # OAuth2 token type, not a secret
    expires_in: int = Field(description="Access token lifetime in seconds.")


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRole
    created_at: datetime
