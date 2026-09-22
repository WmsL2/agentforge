"""Workspace CRUD and membership management routes."""

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, WorkspaceSvc
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceList,
    WorkspaceMemberCreate,
    WorkspaceMemberRead,
    WorkspaceMemberUpdate,
    WorkspaceRead,
    WorkspaceUpdate,
)

router = APIRouter()


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(data: WorkspaceCreate, workspace_service: WorkspaceSvc, current_user: CurrentUser):
    return await workspace_service.create_workspace(current_user.id, data)


@router.get("", response_model=WorkspaceList)
async def list_workspaces(workspace_service: WorkspaceSvc, current_user: CurrentUser):
    return {"items": await workspace_service.list_workspaces(current_user.id)}


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(workspace_id: UUID, workspace_service: WorkspaceSvc, current_user: CurrentUser):
    return await workspace_service.get_workspace(workspace_id, current_user.id)


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
async def update_workspace(
    workspace_id: UUID,
    data: WorkspaceUpdate,
    workspace_service: WorkspaceSvc,
    current_user: CurrentUser,
):
    return await workspace_service.update_workspace(workspace_id, current_user.id, data)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_workspace(workspace_id: UUID, workspace_service: WorkspaceSvc, current_user: CurrentUser):
    await workspace_service.delete_workspace(workspace_id, current_user.id)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberRead])
async def list_members(workspace_id: UUID, workspace_service: WorkspaceSvc, current_user: CurrentUser):
    return await workspace_service.list_members(workspace_id, current_user.id)


@router.post(
    "/{workspace_id}/members", response_model=WorkspaceMemberRead, status_code=status.HTTP_201_CREATED
)
async def add_member(
    workspace_id: UUID,
    data: WorkspaceMemberCreate,
    workspace_service: WorkspaceSvc,
    current_user: CurrentUser,
):
    return await workspace_service.add_member(workspace_id, current_user.id, data)


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberRead)
async def update_member(
    workspace_id: UUID,
    user_id: UUID,
    data: WorkspaceMemberUpdate,
    workspace_service: WorkspaceSvc,
    current_user: CurrentUser,
):
    return await workspace_service.update_member(workspace_id, current_user.id, user_id, data)


@router.delete(
    "/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_member(
    workspace_id: UUID, user_id: UUID, workspace_service: WorkspaceSvc, current_user: CurrentUser
):
    await workspace_service.delete_member(workspace_id, current_user.id, user_id)
