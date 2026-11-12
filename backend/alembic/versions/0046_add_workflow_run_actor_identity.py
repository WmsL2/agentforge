"""Persist the authenticated actor that submitted a workflow run.

Revision ID: 0046_add_workflow_run_actor_identity
Revises: 0045_create_knowledge_vector_index
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0046_add_workflow_run_actor_identity"
down_revision = "0045_create_knowledge_vector_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "workflow_runs_actor_user_id_fkey",
        "workflow_runs",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_workflow_runs_actor_user_id",
        "workflow_runs",
        ["actor_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_actor_user_id", table_name="workflow_runs")
    op.drop_constraint(
        "workflow_runs_actor_user_id_fkey",
        "workflow_runs",
        type_="foreignkey",
    )
    op.drop_column("workflow_runs", "actor_user_id")
