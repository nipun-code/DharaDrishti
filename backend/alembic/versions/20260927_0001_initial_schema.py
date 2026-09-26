"""Initial schema: users, acts, documents, chunks (pgvector + tsvector), section_mappings,
query_logs, feedback, eval_runs.

Revision ID: 0001
Revises:
Create Date: 2026-09-27
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384  # frozen here on purpose: migrations must not change if app constants do
TSV_EXPRESSION = "to_tsvector('english'::regconfig, coalesce(section_title, '') || ' ' || text)"


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column(
        "id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_user_role"),
    )

    op.create_table(
        "acts",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("short_code", sa.String(32), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_file", sa.String(255), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_acts"),
        sa.UniqueConstraint("short_code", name="uq_acts_short_code"),
        sa.CheckConstraint("status IN ('in_force', 'repealed')", name="ck_acts_act_status"),
    )

    op.create_table(
        "documents",
        _uuid_pk(),
        sa.Column("act_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("chunks_count", sa.Integer(), server_default="0", nullable=False),
        _created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.ForeignKeyConstraint(
            ["act_id"], ["acts.id"], name="fk_documents_act_id_acts", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("sha256", name="uq_documents_sha256"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_documents_document_status",
        ),
    )
    op.create_index("ix_documents_act_id", "documents", ["act_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("act_id", sa.Integer(), nullable=False),
        sa.Column("chapter_number", sa.String(32), nullable=True),
        sa.Column("chapter_title", sa.Text(), nullable=True),
        sa.Column("section_number", sa.String(32), nullable=False),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column("subsection", sa.String(64), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(TSV_EXPRESSION, persisted=True),
            nullable=False,
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["act_id"], ["acts.id"], name="fk_chunks_act_id_acts", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_act_id_section_number", "chunks", ["act_id", "section_number"])
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "section_mappings",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("from_act", sa.String(32), nullable=False),
        sa.Column("from_section", sa.String(32), nullable=False),
        sa.Column("to_act", sa.String(32), nullable=False),
        sa.Column("to_section", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_section_mappings"),
        sa.UniqueConstraint(
            "from_act", "from_section", "to_act", "to_section", name="uq_section_mappings_from_to"
        ),
    )
    op.create_index("ix_section_mappings_from", "section_mappings", ["from_act", "from_section"])
    op.create_index("ix_section_mappings_to", "section_mappings", ["to_act", "to_section"])

    op.create_table(
        "query_logs",
        _uuid_pk(),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column(
            "retrieved_chunk_ids",
            postgresql.ARRAY(sa.BigInteger()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("refused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column(
            "guardrail_flags",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_query_logs"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_query_logs_user_id_users", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_query_logs_user_id", "query_logs", ["user_id"])
    op.create_index("ix_query_logs_created_at", "query_logs", ["created_at"])

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("query_log_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
        sa.ForeignKeyConstraint(
            ["query_log_id"],
            ["query_logs.id"],
            name="fk_feedback_query_log_id_query_logs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_feedback_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("query_log_id", "user_id", name="uq_feedback_query_log_id_user_id"),
        sa.CheckConstraint("rating IN (-1, 1)", name="ck_feedback_rating_is_plus_or_minus_one"),
    )
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])

    op.create_table(
        "eval_runs",
        _uuid_pk(),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("per_question", postgresql.JSONB(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_eval_runs"),
    )
    op.create_index("ix_eval_runs_created_at", "eval_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("feedback")
    op.drop_table("query_logs")
    op.drop_table("section_mappings")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("acts")
    op.drop_table("users")
    # The vector extension is left installed: other database objects may depend on it and
    # re-creating it requires superuser rights on some hosts.
