import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.types import created_at_column, str_enum, uuid_pk


class EvalRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Filled in when the (async) run completes.
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    per_question: Mapped[list[Any] | None] = mapped_column(JSONB)
    # Not in the original data model; needed to show running/failed runs and progress.
    status: Mapped[EvalRunStatus] = mapped_column(
        str_enum(EvalRunStatus, "eval_run_status"),
        nullable=False,
        default=EvalRunStatus.PENDING,
        server_default=EvalRunStatus.PENDING.value,
    )
    progress: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column(index=True)

    __table_args__ = (CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),)
