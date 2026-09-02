"""align workflow updated_at with the ORM timestamp contract

Revision ID: 0034_align_workflow_updated_at
Revises: 0033_create_workflow_runs
"""

import sqlalchemy as sa

from alembic import op

revision = "0034_align_workflow_updated_at"
down_revision = "0033_create_workflow_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "workflows",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE workflows
            SET updated_at = COALESCE(updated_at, created_at, now())
            WHERE updated_at IS NULL
            """
        )
    )
    op.alter_column(
        "workflows",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
        nullable=False,
        server_default=sa.text("now()"),
    )
