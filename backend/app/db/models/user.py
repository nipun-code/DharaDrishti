import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import UserRole
from app.db.models.types import created_at_column, str_enum, uuid_pk


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Stored normalized to lower case by the service layer.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        str_enum(UserRole, "user_role"), nullable=False, default=UserRole.USER
    )
    created_at: Mapped[datetime] = created_at_column()
