import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.types import created_at_column, uuid_pk


class QueryLog(Base):
    """One answered (or refused) query. Text fields must be PII-redacted before insert."""

    __tablename__ = "query_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text)
    retrieved_chunk_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, default=list, server_default=text("'{}'")
    )
    answer: Mapped[str | None] = mapped_column(Text)
    refused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    guardrail_flags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    cache_hit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = created_at_column(index=True)
