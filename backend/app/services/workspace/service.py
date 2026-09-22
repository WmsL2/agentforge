"""Workspace application service with transaction ownership left to the caller."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
)
from app.repositories import user as user_repo
from app.repositories import workspace as workspace_repo
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspacePermission, WorkspaceRole

if TYPE_CHECKING:
    from app.schemas.workspace import (
        WorkspaceCreate,
        WorkspaceMemberCreate,
        WorkspaceMemberUpdate,
        WorkspaceUpdate,
    )


class WorkspaceService:
    """Coordinate workspace persistence and its authorization boundary."""

    def __init__(self, db: AsyncSession, authorization: WorkspaceAuthorizationService):
        self._db = db
        self._authorization = authorization

    async def create_workspace(self, actor_user_id: UUID, data: WorkspaceCreate):
        workspace = await workspace_repo.create_workspace(
            self._db,
            name=data.name,
            created_by_user_id=actor_user_id,
        )
        await workspace_repo.create_membership(
            self._db,
            workspace_id=workspace.id,
            user_id=actor_user_id,
            role=WorkspaceRole.OWNER,
        )
        return workspace

    async def list_workspaces(self, actor_user_id: UUID):
        return await workspace_repo.list_workspaces_by_user(self._db, actor_user_id)

    async def get_workspace(self, workspace_id: UUID, actor_user_id: UUID):
        await self._authorization.require_membership(workspace_id, actor_user_id)
        workspace = await workspace_repo.get_workspace_by_id(self._db, workspace_id)
        if workspace is None:
            raise NotFoundError(message="Workspace not found")
        return workspace

    async def update_workspace(self, workspace_id: UUID, actor_user_id: UUID, data: WorkspaceUpdate):
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.WORKSPACE_MANAGE
        )
        workspace = await workspace_repo.get_workspace_by_id(self._db, workspace_id)
        if workspace is None:
            raise NotFoundError(message="Workspace not found")
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return workspace
        return await workspace_repo.update_workspace(
            self._db, db_workspace=workspace, update_data=update_data
        )

    async def delete_workspace(self, workspace_id: UUID, actor_user_id: UUID) -> None:
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.WORKSPACE_MANAGE
        )
        if not await workspace_repo.delete_workspace(self._db, workspace_id):
            raise NotFoundError(message="Workspace not found")

    async def list_members(self, workspace_id: UUID, actor_user_id: UUID):
        await self._authorization.require_membership(workspace_id, actor_user_id)
        return await workspace_repo.list_memberships_by_workspace(self._db, workspace_id)

    async def add_member(
        self, workspace_id: UUID, actor_user_id: UUID, data: WorkspaceMemberCreate
    ):
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.MEMBER_MANAGE
        )
        self._reject_owner_assignment(data.role)
        if await user_repo.get_by_id(self._db, data.user_id) is None:
            raise NotFoundError(message="User not found")
        if await workspace_repo.get_membership(
            self._db, workspace_id=workspace_id, user_id=data.user_id
        ) is not None:
            raise AlreadyExistsError(message="Workspace member already exists")
        return await workspace_repo.create_membership(
            self._db,
            workspace_id=workspace_id,
            user_id=data.user_id,
            role=data.role,
        )

    async def update_member(
        self,
        workspace_id: UUID,
        actor_user_id: UUID,
        user_id: UUID,
        data: WorkspaceMemberUpdate,
    ):
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.MEMBER_MANAGE
        )
        self._reject_owner_assignment(data.role)
        membership = await workspace_repo.get_membership(
            self._db, workspace_id=workspace_id, user_id=user_id
        )
        if membership is None:
            raise NotFoundError(message="Workspace member not found")
        self._reject_owner_membership(membership.workspace_role)
        return await workspace_repo.update_membership_role(
            self._db, db_membership=membership, role=data.role
        )

    async def delete_member(self, workspace_id: UUID, actor_user_id: UUID, user_id: UUID) -> None:
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.MEMBER_MANAGE
        )
        membership = await workspace_repo.get_membership(
            self._db, workspace_id=workspace_id, user_id=user_id
        )
        if membership is None:
            raise NotFoundError(message="Workspace member not found")
        self._reject_owner_membership(membership.workspace_role)
        await workspace_repo.delete_membership(
            self._db, workspace_id=workspace_id, user_id=user_id
        )

    @staticmethod
    def _reject_owner_assignment(role: WorkspaceRole) -> None:
        if role is WorkspaceRole.OWNER:
            raise ValidationError(
                message="Owner role cannot be assigned through membership management",
                code="WORKSPACE_OWNER_ROLE_RESERVED",
            )

    @staticmethod
    def _reject_owner_membership(role: WorkspaceRole) -> None:
        if role is WorkspaceRole.OWNER:
            raise AuthorizationError(
                message="Owner membership cannot be modified through membership management",
                code="WORKSPACE_OWNER_MEMBERSHIP_PROTECTED",
            )
