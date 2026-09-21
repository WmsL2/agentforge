"""Tests for the workspace authorization boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.repositories import workspace as workspace_repo
from app.services.workspace import (
    WorkspaceAuthorizationService,
    WorkspacePermission,
    WorkspaceRole,
)


def membership(role: WorkspaceRole) -> SimpleNamespace:
    return SimpleNamespace(workspace_role=role)


@pytest.mark.anyio
async def test_require_membership_returns_persisted_membership() -> None:
    db = AsyncMock()
    stored = membership(WorkspaceRole.MEMBER)
    service = WorkspaceAuthorizationService(db)
    workspace_id, actor_user_id = uuid4(), uuid4()

    with patch(
        "app.services.workspace.authorization.workspace_repo.get_membership",
        AsyncMock(return_value=stored),
    ) as get_membership:
        assert await service.require_membership(workspace_id, actor_user_id) is stored

    get_membership.assert_awaited_once_with(
        db, workspace_id=workspace_id, user_id=actor_user_id
    )
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_require_membership_hides_non_members_as_not_found() -> None:
    db = AsyncMock()
    service = WorkspaceAuthorizationService(db)

    with patch(
        "app.services.workspace.authorization.workspace_repo.get_membership",
        AsyncMock(return_value=None),
    ), patch.object(workspace_repo, "get_workspace_by_id", AsyncMock()) as get_workspace, pytest.raises(
        NotFoundError
    ) as error:
        await service.require_membership(uuid4(), uuid4())

    assert (error.value.status_code, error.value.message) == (404, "Workspace not found")
    get_workspace.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("role", "permission"),
    [
        (WorkspaceRole.MEMBER, WorkspacePermission.WORKFLOW_RUN),
        (WorkspaceRole.ADMIN, WorkspacePermission.APPROVAL_DECIDE),
        (WorkspaceRole.OWNER, WorkspacePermission.WORKSPACE_MANAGE),
    ],
)
async def test_require_permission_allows_granted_role_permission(
    role: WorkspaceRole, permission: WorkspacePermission
) -> None:
    service = WorkspaceAuthorizationService(AsyncMock())
    stored = membership(role)

    with patch.object(service, "require_membership", AsyncMock(return_value=stored)):
        assert await service.require_permission(uuid4(), uuid4(), permission) is stored


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("role", "permission"),
    [
        (WorkspaceRole.MEMBER, WorkspacePermission.APPROVAL_DECIDE),
        (WorkspaceRole.ADMIN, WorkspacePermission.WORKSPACE_MANAGE),
    ],
)
async def test_require_permission_returns_403_for_member_without_permission(
    role: WorkspaceRole, permission: WorkspacePermission
) -> None:
    service = WorkspaceAuthorizationService(AsyncMock())

    with patch.object(service, "require_membership", AsyncMock(return_value=membership(role))), pytest.raises(
        AuthorizationError
    ) as error:
        await service.require_permission(uuid4(), uuid4(), permission)

    assert error.value.status_code == 403
    assert error.value.code == "WORKSPACE_PERMISSION_DENIED"
    assert error.value.message == f"Workspace permission '{permission.value}' required"


@pytest.mark.anyio
async def test_require_permission_hides_non_members_as_not_found() -> None:
    service = WorkspaceAuthorizationService(AsyncMock())

    with patch.object(service, "require_membership", AsyncMock(side_effect=NotFoundError(message="Workspace not found"))), pytest.raises(
        NotFoundError
    ) as error:
        await service.require_permission(uuid4(), uuid4(), WorkspacePermission.WORKFLOW_READ)

    assert error.value.status_code == 404
