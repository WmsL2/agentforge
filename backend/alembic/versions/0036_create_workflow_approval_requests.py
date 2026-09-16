"""create workflow approval requests

Revision ID: 0036_create_workflow_approval_requests
Revises: 0035_create_workflow_checkpoints
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0036_create_workflow_approval_requests"
down_revision = "0035_create_workflow_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_table(
        "approval_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_revision", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decided_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "node_id"),
        sa.CheckConstraint("workflow_revision >= 1", name="workflow_revision_positive"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status_valid"),
    )
    op.create_index(
        "approval_requests_run_id_status_idx", "approval_requests", ["run_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("approval_requests_run_id_status_idx", table_name="approval_requests")
    op.drop_table("approval_requests")
