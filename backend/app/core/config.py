"""Application settings, loaded from environment variables / .env via pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
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

    # --- Ingestion ---------------------------------------------------------
    max_upload_mb: int = Field(default=25, ge=1, le=500)
    upload_dir: Path = Field(default=Path("uploads"), description="Where uploaded PDFs are kept.")
    data_dir: Path = Field(default=Path("../data"), description="User-provided data (mappings).")
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = Field(default=32, ge=1)
    embedding_device: str = "cpu"
    chunk_max_tokens: int = Field(default=600, ge=50)
    chunk_overlap_tokens: int = Field(default=80, ge=0)
    ingestion_job_timeout_seconds: int = Field(default=1800, ge=60)

    # --- Retrieval ---------------------------------------------------------
    # bge models expect this prefix on queries (not on passages).
    embedding_query_instruction: str = "Represent this sentence for searching relevant passages: "
    reranker_model_name: str = "BAAI/bge-reranker-base"
    reranker_max_length: int = Field(default=512, ge=64)
    reranker_batch_size: int = Field(default=16, ge=1)
    retrieval_candidates: int = Field(
        default=20, ge=1, le=200, description="Per search, per query."
    )
    retrieval_top_k: int = Field(default=5, ge=1, le=50)
    rerank_candidates: int = Field(default=20, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1)
    section_lookup_max_chunks: int = Field(default=3, ge=1, le=20)
    max_section_refs: int = Field(default=5, ge=1, le=20)
    hnsw_ef_search: int = Field(default=100, ge=10, le=1000)

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> Self:
        if self.chunk_overlap_tokens >= self.chunk_max_tokens // 2:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be less than half of CHUNK_MAX_TOKENS")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide (immutable) settings instance."""
    return Settings()  # values come from the environment
