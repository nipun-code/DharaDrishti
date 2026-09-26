import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.types import created_at_column, uuid_pk


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Filled in when the (async) run completes.
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    per_question: Mapped[list[Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column(index=True)
