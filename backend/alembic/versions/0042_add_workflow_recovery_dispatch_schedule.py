"""Add durable fair-scan dispatch timestamps for workflow recovery.

Revision ID: 0042_add_workflow_recovery_dispatch_schedule
Revises: 0041_add_workflow_execution_claim_lease
"""

from alembic import op
import sqlalchemy as sa

revision = "0042_add_workflow_recovery_dispatch_schedule"
down_revision = "0041_add_workflow_execution_claim_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("recovery_last_dispatched_at", sa.DateTime(timezone=True)))
    op.add_column("workflow_runs", sa.Column("recovery_next_dispatch_at", sa.DateTime(timezone=True)))
    op.create_index(
        "workflow_runs_recovery_dispatch_idx",
        "workflow_runs",
        ["recovery_next_dispatch_at", "recovery_last_dispatched_at", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("workflow_runs_recovery_dispatch_idx", table_name="workflow_runs")
    op.drop_column("workflow_runs", "recovery_next_dispatch_at")
    op.drop_column("workflow_runs", "recovery_last_dispatched_at")
