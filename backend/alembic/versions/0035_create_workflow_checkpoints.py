"""create workflow checkpoints table

Revision ID: 0035_create_workflow_checkpoints
Revises: 0034_align_workflow_updated_at
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0035_create_workflow_checkpoints"
down_revision = "0034_align_workflow_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_checkpoints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_revision", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("completed_node_ids", JSONB, nullable=False),
        sa.Column("node_outputs", JSONB, nullable=False),
        sa.Column("pending_node_id", sa.String(), nullable=True),
        sa.Column("interrupt", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("run_id", "sequence"),
        sa.CheckConstraint("sequence >= 1", name="sequence_positive"),
    )


def downgrade() -> None:
    op.drop_table("workflow_checkpoints")
