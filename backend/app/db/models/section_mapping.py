from sqlalchemy import Identity, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SectionMapping(Base):
    """A verified old-act -> new-act section correspondence (loaded from data/mappings only)."""

    __tablename__ = "section_mappings"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    from_act: Mapped[str] = mapped_column(String(32), nullable=False)
    from_section: Mapped[str] = mapped_column(String(32), nullable=False)
    to_act: Mapped[str] = mapped_column(String(32), nullable=False)
    to_section: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "from_act", "from_section", "to_act", "to_section", name="uq_section_mappings_from_to"
        ),
        Index("ix_section_mappings_from", "from_act", "from_section"),
        Index("ix_section_mappings_to", "to_act", "to_section"),
    )
