"""Add status, progress, error and finished_at to eval_runs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
    )
    op.add_column(
        "eval_runs",
        sa.Column("progress", sa.SmallInteger(), server_default="0", nullable=False),
    )
    op.add_column("eval_runs", sa.Column("error", sa.Text(), nullable=True))
    op.add_column(
        "eval_runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_eval_runs_eval_run_status",
        "eval_runs",
        "status IN ('pending', 'running', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_eval_runs_progress_range", "eval_runs", "progress BETWEEN 0 AND 100"
    )


def downgrade() -> None:
    op.drop_constraint("ck_eval_runs_progress_range", "eval_runs", type_="check")
    op.drop_constraint("ck_eval_runs_eval_run_status", "eval_runs", type_="check")
    for column in ("finished_at", "error", "progress", "status"):
        op.drop_column("eval_runs", column)
