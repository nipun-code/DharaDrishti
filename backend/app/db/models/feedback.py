import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Identity,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.types import created_at_column


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    query_log_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("query_logs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("rating IN (-1, 1)", name="rating_is_plus_or_minus_one"),
        # One vote per user per answer.
        UniqueConstraint("query_log_id", "user_id", name="uq_feedback_query_log_id_user_id"),
    )
