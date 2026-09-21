"""Workspace authorization boundary backed by persisted memberships."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.repositories import workspace as workspace_repo
from app.services.workspace.domain import WorkspacePermission
from app.services.workspace.policy import has_workspace_permission

if TYPE_CHECKING:
    from app.db.models.workspace import WorkspaceMembership


class WorkspaceAuthorizationService:
    """Authorize an actor solely through the target workspace membership."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def require_membership(
        self, workspace_id: UUID, actor_user_id: UUID
    ) -> WorkspaceMembership:
        """Return membership or hide the workspace with a not-found response."""
        membership = await workspace_repo.get_membership(
            self._db,
            workspace_id=workspace_id,
            user_id=actor_user_id,
        )
        if membership is None:
            raise NotFoundError(message="Workspace not found")
        return membership

    async def require_permission(
        self,
        workspace_id: UUID,
        actor_user_id: UUID,
        permission: WorkspacePermission,
    ) -> WorkspaceMembership:
        """Return membership when its role grants the requested permission."""
        membership = await self.require_membership(workspace_id, actor_user_id)
        if not has_workspace_permission(membership.workspace_role, permission):
            raise AuthorizationError(
                message=f"Workspace permission '{permission.value}' required",
                code="WORKSPACE_PERMISSION_DENIED",
            )
        return membership
