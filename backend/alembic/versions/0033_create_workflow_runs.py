"""create workflow runs table

Revision ID: 0033_create_workflow_runs
Revises: 0032_create_workflows
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0033_create_workflow_runs"
down_revision = "0032_create_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_revision", sa.Integer(), nullable=False),
        sa.Column("definition_snapshot", JSONB, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input", JSONB, nullable=False),
        sa.Column("node_outputs", JSONB, nullable=False),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("error", JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("workflow_runs_workflow_id_idx"),
        "workflow_runs",
        ["workflow_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("workflow_runs_workflow_id_idx"),
        table_name="workflow_runs",
    )
    op.drop_table("workflow_runs")
