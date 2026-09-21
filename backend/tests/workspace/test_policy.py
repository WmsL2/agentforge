"""Tests for the static workspace RBAC policy."""

import pytest

from app.services.workspace import (
    WorkspacePermission,
    WorkspaceRole,
    has_workspace_permission,
    permissions_for_role,
)

MEMBER_PERMISSIONS = {
    WorkspacePermission.WORKFLOW_READ,
    WorkspacePermission.WORKFLOW_CREATE,
    WorkspacePermission.WORKFLOW_EDIT,
    WorkspacePermission.WORKFLOW_RUN,
    WorkspacePermission.RUN_READ,
}
ADMIN_PERMISSIONS = MEMBER_PERMISSIONS | {
    WorkspacePermission.WORKFLOW_DELETE,
    WorkspacePermission.APPROVAL_DECIDE,
    WorkspacePermission.MEMBER_MANAGE,
}


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (WorkspaceRole.MEMBER, MEMBER_PERMISSIONS),
        (WorkspaceRole.ADMIN, ADMIN_PERMISSIONS),
        (WorkspaceRole.OWNER, set(WorkspacePermission)),
    ],
)
def test_role_permission_matrix_is_exact(
    role: WorkspaceRole, expected: set[WorkspacePermission]
) -> None:
    assert permissions_for_role(role) == expected
    assert {
        permission
        for permission in WorkspacePermission
        if has_workspace_permission(role, permission)
    } == expected


def test_permissions_for_role_returns_an_immutable_set() -> None:
    permissions = permissions_for_role(WorkspaceRole.MEMBER)

    assert isinstance(permissions, frozenset)
    with pytest.raises(AttributeError):
        permissions.add(WorkspacePermission.WORKFLOW_DELETE)  # type: ignore[attr-defined]
