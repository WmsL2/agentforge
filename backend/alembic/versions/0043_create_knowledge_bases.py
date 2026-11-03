"""Create workspace-scoped knowledge bases.

Revision ID: 0043_create_knowledge_bases
Revises: 0042_add_workflow_recovery_dispatch_schedule
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0043_create_knowledge_bases"
down_revision = "0042_add_workflow_recovery_dispatch_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            name="knowledge_bases_workspace_id_name_key",
        ),
    )
    op.create_index(
        "knowledge_bases_workspace_created_id_idx",
        "knowledge_bases",
        ["workspace_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "knowledge_bases_workspace_created_id_idx",
        table_name="knowledge_bases",
    )
    op.drop_table("knowledge_bases")
