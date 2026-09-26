from datetime import datetime

from sqlalchemy import Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import ActStatus
from app.db.models.types import created_at_column, str_enum


class Act(Base):
    __tablename__ = "acts"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    short_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ActStatus] = mapped_column(
        str_enum(ActStatus, "act_status"), nullable=False, default=ActStatus.IN_FORCE
    )
    source_file: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at_column()
