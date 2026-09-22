"""HTTP schemas for Workspace resources and memberships."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.services.workspace.domain import WorkspaceRole


class WorkspaceCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=255)


class WorkspaceUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class WorkspaceRead(BaseSchema):
    id: UUID
    name: str
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime | None


class WorkspaceList(BaseSchema):
    items: list[WorkspaceRead]


class WorkspaceMemberCreate(BaseSchema):
    user_id: UUID
    role: WorkspaceRole = WorkspaceRole.MEMBER


class WorkspaceMemberUpdate(BaseSchema):
    role: WorkspaceRole


class WorkspaceMemberRead(BaseSchema):
    workspace_id: UUID
    user_id: UUID
    role: WorkspaceRole
    created_at: datetime
    updated_at: datetime | None
