"""Application settings, loaded from environment variables / .env via pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Environment = Literal["development", "test", "production"]

MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """All runtime configuration. Every field maps to an upper-case env var of the same name."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "DharaDrishti"
    app_version: str = "0.1.0"
    environment: Environment = "development"
    log_level: LogLevel = "INFO"

    # Secrets / connection strings: no defaults for anything containing credentials.
    database_url: SecretStr = Field(
        description="SQLAlchemy async URL, e.g. postgresql+asyncpg://user:pass@host:5432/db",
    )
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    redis_url: str = "redis://localhost:6379/0"

    request_id_header: str = "X-Request-ID"
    health_check_timeout_seconds: float = Field(default=2.0, gt=0)

    # --- Auth -------------------------------------------------------------
    jwt_secret_key: SecretStr = Field(description="HMAC key for signing JWTs (>= 32 chars).")
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)
    bcrypt_rounds: int = Field(default=12, ge=4, le=31)

    @field_validator("jwt_secret_key")
    @classmethod
    def _secret_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET_KEY must be at least {MIN_JWT_SECRET_LENGTH} characters")
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide (immutable) settings instance."""
    return Settings()  # values come from the environment
