"""Knowledge base application service and workspace authorization boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.repositories import knowledge as knowledge_repo
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspacePermission

if TYPE_CHECKING:
    from app.schemas.knowledge import KnowledgeBaseCreate, KnowledgeBaseUpdate


_NAME_UNIQUE_CONSTRAINT = "knowledge_bases_workspace_id_name_key"


class KnowledgeBaseService:
    """Coordinate workspace-scoped knowledge CRUD without owning transactions."""

    def __init__(self, db: AsyncSession, authorization: WorkspaceAuthorizationService):
        self._db = db
        self._authorization = authorization

    async def create_knowledge_base(
        self, workspace_id: UUID, actor_user_id: UUID, data: KnowledgeBaseCreate
    ):
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_CREATE
        )
        if (
            await knowledge_repo.get_by_workspace_and_name(
                self._db, workspace_id=workspace_id, name=data.name
            )
            is not None
        ):
            raise AlreadyExistsError(message="Knowledge base name already exists in workspace")
        try:
            return await knowledge_repo.create(
                self._db,
                workspace_id=workspace_id,
                name=data.name,
                description=data.description,
                created_by_user_id=actor_user_id,
            )
        except IntegrityError as exception:
            self._raise_name_conflict(exception)
            raise

    async def list_knowledge_bases(
        self, workspace_id: UUID, actor_user_id: UUID, *, skip: int, limit: int
    ):
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_READ
        )
        items = await knowledge_repo.list_by_workspace(
            self._db, workspace_id=workspace_id, skip=skip, limit=limit
        )
        total = await knowledge_repo.count_by_workspace(self._db, workspace_id=workspace_id)
        return items, total

    async def get_knowledge_base(
        self, workspace_id: UUID, knowledge_base_id: UUID, actor_user_id: UUID
    ):
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_READ
        )
        return await self._get_or_404(workspace_id, knowledge_base_id)

    async def update_knowledge_base(
        self,
        workspace_id: UUID,
        knowledge_base_id: UUID,
        actor_user_id: UUID,
        data: KnowledgeBaseUpdate,
    ):
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_EDIT
        )
        knowledge_base = await self._get_or_404(workspace_id, knowledge_base_id)
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return knowledge_base
        if "name" in update_data and update_data["name"] != knowledge_base.name:
            duplicate = await knowledge_repo.get_by_workspace_and_name(
                self._db, workspace_id=workspace_id, name=update_data["name"]
            )
            if duplicate is not None:
                raise AlreadyExistsError(message="Knowledge base name already exists in workspace")
        try:
            return await knowledge_repo.update(
                self._db,
                db_knowledge_base=knowledge_base,
                update_data=update_data,
            )
        except IntegrityError as exception:
            self._raise_name_conflict(exception)
            raise

    async def delete_knowledge_base(
        self, workspace_id: UUID, knowledge_base_id: UUID, actor_user_id: UUID
    ) -> None:
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_DELETE
        )
        knowledge_base = await self._get_or_404(workspace_id, knowledge_base_id)
        await knowledge_repo.delete(self._db, db_knowledge_base=knowledge_base)

    async def _get_or_404(self, workspace_id: UUID, knowledge_base_id: UUID):
        knowledge_base = await knowledge_repo.get_by_workspace_and_id(
            self._db,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
        )
        if knowledge_base is None:
            raise NotFoundError(message="Knowledge base not found")
        return knowledge_base

    @staticmethod
    def _raise_name_conflict(exception: IntegrityError) -> None:
        """Map only the expected PostgreSQL uniqueness race to a domain conflict."""
        current: BaseException | None = exception.orig
        while current is not None:
            diagnostic = getattr(current, "diag", None)
            constraint_name = getattr(current, "constraint_name", None) or getattr(
                diagnostic, "constraint_name", None
            )
            if constraint_name == _NAME_UNIQUE_CONSTRAINT:
                raise AlreadyExistsError(
                    message="Knowledge base name already exists in workspace"
                ) from exception
            current = current.__cause__
