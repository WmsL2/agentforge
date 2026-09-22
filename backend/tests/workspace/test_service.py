"""Unit tests for Workspace application service transaction and RBAC boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, ValidationError
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberUpdate,
    WorkspaceUpdate,
)
from app.services.workspace.domain import WorkspaceRole
from app.services.workspace.service import WorkspaceService


def make_service() -> tuple[WorkspaceService, AsyncMock, AsyncMock]:
    db = AsyncMock()
    authorization = AsyncMock()
    return WorkspaceService(db, authorization), db, authorization


@pytest.mark.anyio
async def test_create_workspace_adds_creator_as_owner_without_committing() -> None:
    service, db, _ = make_service()
    actor_id = uuid4()
    workspace = SimpleNamespace(id=uuid4())
    with patch(
        "app.services.workspace.service.workspace_repo.create_workspace", AsyncMock(return_value=workspace)
    ) as create_workspace, patch(
        "app.services.workspace.service.workspace_repo.create_membership", AsyncMock()
    ) as create_membership:
        assert await service.create_workspace(actor_id, WorkspaceCreate(name="Team")) is workspace

    create_workspace.assert_awaited_once_with(db, name="Team", created_by_user_id=actor_id)
    create_membership.assert_awaited_once_with(
        db, workspace_id=workspace.id, user_id=actor_id, role=WorkspaceRole.OWNER
    )
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_list_and_get_workspace_use_membership_boundary_first() -> None:
    service, db, authorization = make_service()
    actor_id, workspace_id = uuid4(), uuid4()
    workspace = SimpleNamespace(id=workspace_id)
    with patch(
        "app.services.workspace.service.workspace_repo.list_workspaces_by_user", AsyncMock(return_value=[workspace])
    ) as list_workspaces, patch(
        "app.services.workspace.service.workspace_repo.get_workspace_by_id", AsyncMock(return_value=workspace)
    ) as get_workspace:
        assert await service.list_workspaces(actor_id) == [workspace]
        assert await service.get_workspace(workspace_id, actor_id) is workspace

    list_workspaces.assert_awaited_once_with(db, actor_id)
    authorization.require_membership.assert_awaited_once_with(workspace_id, actor_id)
    get_workspace.assert_awaited_once_with(db, workspace_id)


@pytest.mark.anyio
async def test_update_workspace_requires_owner_permission_and_skips_empty_patch() -> None:
    service, db, authorization = make_service()
    actor_id, workspace_id = uuid4(), uuid4()
    workspace = SimpleNamespace(id=workspace_id, name="Existing")
    with patch(
        "app.services.workspace.service.workspace_repo.get_workspace_by_id", AsyncMock(return_value=workspace)
    ), patch(
        "app.services.workspace.service.workspace_repo.update_workspace", AsyncMock()
    ) as update_workspace:
        assert await service.update_workspace(workspace_id, actor_id, WorkspaceUpdate()) is workspace

    authorization.require_permission.assert_awaited_once()
    update_workspace.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_authorization_rejection_prevents_workspace_mutation() -> None:
    service, _, authorization = make_service()
    authorization.require_permission.side_effect = AuthorizationError(message="denied")
    with patch(
        "app.services.workspace.service.workspace_repo.update_workspace", AsyncMock()
    ) as update_workspace, pytest.raises(AuthorizationError):
        await service.update_workspace(uuid4(), uuid4(), WorkspaceUpdate(name="Nope"))
    update_workspace.assert_not_awaited()


@pytest.mark.anyio
async def test_add_member_rejects_owner_and_duplicate_before_create() -> None:
    service, _, _ = make_service()
    with pytest.raises(ValidationError) as error:
        await service.add_member(uuid4(), uuid4(), WorkspaceMemberCreate(user_id=uuid4(), role=WorkspaceRole.OWNER))
    assert error.value.code == "WORKSPACE_OWNER_ROLE_RESERVED"

    with patch(
        "app.services.workspace.service.user_repo.get_by_id", AsyncMock(return_value=SimpleNamespace())
    ), patch(
        "app.services.workspace.service.workspace_repo.get_membership", AsyncMock(return_value=SimpleNamespace())
    ), patch(
        "app.services.workspace.service.workspace_repo.create_membership", AsyncMock()
    ) as create_membership, pytest.raises(Exception, match="Workspace member already exists"):
        await service.add_member(uuid4(), uuid4(), WorkspaceMemberCreate(user_id=uuid4()))
    create_membership.assert_not_awaited()


@pytest.mark.anyio
async def test_owner_membership_cannot_be_updated_or_deleted() -> None:
    service, _, _ = make_service()
    owner = SimpleNamespace(workspace_role=WorkspaceRole.OWNER)
    with patch(
        "app.services.workspace.service.workspace_repo.get_membership", AsyncMock(return_value=owner)
    ):
        with pytest.raises(AuthorizationError) as update_error:
            await service.update_member(uuid4(), uuid4(), uuid4(), WorkspaceMemberUpdate(role=WorkspaceRole.ADMIN))
        with pytest.raises(AuthorizationError) as delete_error:
            await service.delete_member(uuid4(), uuid4(), uuid4())
    assert update_error.value.code == "WORKSPACE_OWNER_MEMBERSHIP_PROTECTED"
    assert delete_error.value.code == "WORKSPACE_OWNER_MEMBERSHIP_PROTECTED"
