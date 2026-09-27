"""Add documents.progress (0-100) for ingestion progress reporting.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("progress", sa.SmallInteger(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_documents_progress_range", "documents", "progress BETWEEN 0 AND 100"
    )


def downgrade() -> None:
    op.drop_constraint("ck_documents_progress_range", "documents", type_="check")
    op.drop_column("documents", "progress")
