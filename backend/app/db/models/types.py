"""Shared column types and helpers for ORM models."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, func, text
from sqlalchemy.orm import Mapped, mapped_column

# Embedding size of BAAI/bge-small-en-v1.5. Changing it requires a migration.
EMBEDDING_DIM = 384


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """VARCHAR column restricted by a named CHECK constraint to the enum's *values*."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


def created_at_column(*, index: bool = False) -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=index
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID primary key, generated in Python and (for raw SQL inserts) by the database."""
    return mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
