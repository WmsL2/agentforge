"""create workflow observability tables

Revision ID: 0037_create_workflow_observability
Revises: 0036_create_workflow_approval_requests
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0037_create_workflow_observability"
down_revision = "0036_create_workflow_approval_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_run_steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("node_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input", JSONB, nullable=False),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("error", JSONB, nullable=True),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "sequence"),
        sa.CheckConstraint("sequence >= 1", name="sequence_positive"),
    )
    op.create_table(
        "workflow_trace_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_id", UUID(as_uuid=True), sa.ForeignKey("workflow_run_steps.id"), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "workflow_trace_events_run_id_created_at_idx",
        "workflow_trace_events",
        ["run_id", "created_at"],
    )
    op.create_index("workflow_trace_events_step_id_idx", "workflow_trace_events", ["step_id"])


def downgrade() -> None:
    op.drop_index("workflow_trace_events_step_id_idx", table_name="workflow_trace_events")
    op.drop_index("workflow_trace_events_run_id_created_at_idx", table_name="workflow_trace_events")
    op.drop_table("workflow_trace_events")
    op.drop_table("workflow_run_steps")
