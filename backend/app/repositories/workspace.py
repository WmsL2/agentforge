"""Workspace persistence primitives without transaction ownership."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workspace import Workspace, WorkspaceMembership
from app.services.workspace import WorkspaceRole


async def get_workspace_by_id(db: AsyncSession, workspace_id: UUID) -> Workspace | None:
    """Return a workspace by identity, if it exists."""
    return await db.get(Workspace, workspace_id)


async def create_workspace(
    db: AsyncSession,
    *,
    name: str,
    created_by_user_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> Workspace:
    """Create a workspace without creating memberships or committing."""
    values: dict[str, Any] = {"name": name, "created_by_user_id": created_by_user_id}
    if workspace_id is not None:
        values["id"] = workspace_id
    workspace = Workspace(**values)
    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)
    return workspace


async def list_workspaces_by_user(db: AsyncSession, user_id: UUID) -> list[Workspace]:
    """List workspaces in which the user has a membership."""
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id == user_id)
        .order_by(Workspace.created_at.desc())
    )
    return list(result.scalars().all())


async def update_workspace(
    db: AsyncSession, *, db_workspace: Workspace, update_data: dict[str, Any]
) -> Workspace:
    """Persist supplied workspace fields without committing."""
    for field, value in update_data.items():
        setattr(db_workspace, field, value)
    db.add(db_workspace)
    await db.flush()
    await db.refresh(db_workspace)
    return db_workspace


async def delete_workspace(db: AsyncSession, workspace_id: UUID) -> bool:
    """Delete a workspace by identity without committing."""
    workspace = await get_workspace_by_id(db, workspace_id)
    if workspace is None:
        return False
    await db.delete(workspace)
    await db.flush()
    return True


async def create_membership(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    role: WorkspaceRole,
) -> WorkspaceMembership:
    """Create a membership without authorization checks or committing."""
    membership = WorkspaceMembership(
        workspace_id=workspace_id,
        user_id=user_id,
        role=role.value,
    )
    db.add(membership)
    await db.flush()
    await db.refresh(membership)
    return membership


async def get_membership(
    db: AsyncSession, *, workspace_id: UUID, user_id: UUID
) -> WorkspaceMembership | None:
    """Return a membership by its composite identity, if it exists."""
    return await db.get(WorkspaceMembership, (workspace_id, user_id))


async def list_memberships_by_workspace(
    db: AsyncSession, workspace_id: UUID
) -> list[WorkspaceMembership]:
    """List a workspace's memberships in stable creation order."""
    result = await db.execute(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.user_id.asc())
    )
    return list(result.scalars().all())


async def update_membership_role(
    db: AsyncSession,
    *,
    db_membership: WorkspaceMembership,
    role: WorkspaceRole,
) -> WorkspaceMembership:
    """Persist one membership role change without committing."""
    db_membership.role = role.value
    db.add(db_membership)
    await db.flush()
    await db.refresh(db_membership)
    return db_membership


async def delete_membership(db: AsyncSession, *, workspace_id: UUID, user_id: UUID) -> bool:
    """Delete a membership by composite identity without committing."""
    membership = await get_membership(db, workspace_id=workspace_id, user_id=user_id)
    if membership is None:
        return False
    await db.delete(membership)
    await db.flush()
    return True
