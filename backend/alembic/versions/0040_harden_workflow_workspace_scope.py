"""harden workflow workspace scope

Revision ID: 0040_harden_workflow_workspace_scope
Revises: 0039_add_workflow_workspace_scope
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, insert

from alembic import op

revision = "0040_harden_workflow_workspace_scope"
down_revision = "0039_add_workflow_workspace_scope"
branch_labels = None
depends_on = None


def personal_workspace_id(user_id: uuid.UUID) -> uuid.UUID:
    """Return the stable personal workspace identity for one legacy user."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"agentforge://personal-workspace/{user_id}")


def upgrade() -> None:
    bind = op.get_bind()
    workspaces = sa.table(
        "workspaces",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("created_by_user_id", UUID(as_uuid=True)),
    )
    memberships = sa.table(
        "workspace_memberships",
        sa.column("workspace_id", UUID(as_uuid=True)),
        sa.column("user_id", UUID(as_uuid=True)),
        sa.column("role", sa.String()),
    )
    workflows = sa.table(
        "workflows",
        sa.column("user_id", UUID(as_uuid=True)),
        sa.column("workspace_id", UUID(as_uuid=True)),
    )
    legacy_user_ids = bind.execute(
        sa.select(workflows.c.user_id)
        .where(workflows.c.workspace_id.is_(None), workflows.c.user_id.is_not(None))
        .distinct()
    ).scalars()
    for user_id in legacy_user_ids:
        workspace_id = personal_workspace_id(user_id)
        bind.execute(
            insert(workspaces)
            .values(
                id=workspace_id,
                name="Personal Workspace",
                created_by_user_id=user_id,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        bind.execute(
            insert(memberships)
            .values(workspace_id=workspace_id, user_id=user_id, role="owner")
            .on_conflict_do_update(
                index_elements=["workspace_id", "user_id"],
                set_={"role": "owner"},
            )
        )
        bind.execute(
            sa.update(workflows)
            .where(workflows.c.user_id == user_id, workflows.c.workspace_id.is_(None))
            .values(workspace_id=workspace_id)
        )

    remaining = bind.scalar(
        sa.select(sa.func.count()).select_from(workflows).where(workflows.c.workspace_id.is_(None))
    )
    if remaining:
        raise RuntimeError(
            "Cannot harden workflows.workspace_id: workflows without a recoverable owner remain."
        )

    op.alter_column(
        "workflows",
        "workspace_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "workflows",
        "workspace_id",
        existing_type=UUID(as_uuid=True),
        nullable=True,
    )
