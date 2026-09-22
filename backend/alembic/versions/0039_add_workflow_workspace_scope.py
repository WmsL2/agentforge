"""add workflow workspace scope

Revision ID: 0039_add_workflow_workspace_scope
Revises: 0038_create_workspaces
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, insert

from alembic import op

revision = "0039_add_workflow_workspace_scope"
down_revision = "0038_create_workspaces"
branch_labels = None
depends_on = None


def personal_workspace_id(user_id: uuid.UUID) -> uuid.UUID:
    """Return the stable personal workspace identity for one legacy user."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"agentforge://personal-workspace/{user_id}")


def upgrade() -> None:
    op.add_column("workflows", sa.Column("workspace_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "workflows_workspace_id_fkey",
        "workflows",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("workflows_workspace_id_idx", "workflows", ["workspace_id"])

    bind = op.get_bind()
    users = sa.table("users", sa.column("id", UUID(as_uuid=True)))
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
    for user_id in bind.execute(sa.select(users.c.id)).scalars():
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
            .on_conflict_do_nothing(index_elements=["workspace_id", "user_id"])
        )
        bind.execute(
            sa.update(workflows)
            .where(workflows.c.user_id == user_id, workflows.c.workspace_id.is_(None))
            .values(workspace_id=workspace_id)
        )

    op.drop_constraint("workflows_user_id_fkey", "workflows", type_="foreignkey")
    op.alter_column("workflows", "user_id", existing_type=UUID(as_uuid=True), nullable=True)
    op.create_foreign_key(
        "workflows_user_id_fkey",
        "workflows",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("workflows_user_id_fkey", "workflows", type_="foreignkey")
    op.execute(
        """
        UPDATE workflows
        SET user_id = workspaces.created_by_user_id
        FROM workspaces
        WHERE workflows.user_id IS NULL
          AND workflows.workspace_id = workspaces.id
          AND workspaces.created_by_user_id IS NOT NULL
        """
    )
    op.alter_column("workflows", "user_id", existing_type=UUID(as_uuid=True), nullable=False)
    op.create_foreign_key(
        "workflows_user_id_fkey",
        "workflows",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("workflows_workspace_id_idx", table_name="workflows")
    op.drop_constraint("workflows_workspace_id_fkey", "workflows", type_="foreignkey")
    op.drop_column("workflows", "workspace_id")
