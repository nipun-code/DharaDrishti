import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Computed, ForeignKey, Identity, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.types import EMBEDDING_DIM, created_at_column

TSV_EXPRESSION = "to_tsvector('english'::regconfig, coalesce(section_title, '') || ' ' || text)"


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    act_id: Mapped[int] = mapped_column(ForeignKey("acts.id", ondelete="CASCADE"), nullable=False)
    chapter_number: Mapped[str | None] = mapped_column(String(32))
    chapter_title: Mapped[str | None] = mapped_column(Text)
    section_number: Mapped[str] = mapped_column(String(32), nullable=False)
    section_title: Mapped[str | None] = mapped_column(Text)
    subsection: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed(TSV_EXPRESSION, persisted=True))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_act_id_section_number", "act_id", "section_number"),
    )
