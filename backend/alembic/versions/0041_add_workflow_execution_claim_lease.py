"""add workflow execution claim and lease

Revision ID: 0041_add_workflow_execution_claim_lease
Revises: 0040_harden_workflow_workspace_scope
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0041_add_workflow_execution_claim_lease"
down_revision = "0040_harden_workflow_workspace_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs", sa.Column("execution_claim_token", UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "workflow_runs",
        sa.Column("execution_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column(
            "execution_claim_generation", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.create_check_constraint(
        "execution_claim_generation_nonnegative", "workflow_runs", "execution_claim_generation >= 0"
    )
    op.create_check_constraint(
        "execution_claim_lease_pair",
        "workflow_runs",
        "(execution_claim_token IS NULL) = (execution_lease_expires_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("execution_claim_lease_pair", "workflow_runs", type_="check")
    op.drop_constraint("execution_claim_generation_nonnegative", "workflow_runs", type_="check")
    op.drop_column("workflow_runs", "execution_claim_generation")
    op.drop_column("workflow_runs", "execution_lease_expires_at")
    op.drop_column("workflow_runs", "execution_claim_token")
