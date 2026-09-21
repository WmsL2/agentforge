"""Tests for pure workspace domain types."""

from app.services.workspace import WorkspacePermission, WorkspaceRole


def test_workspace_roles_have_only_the_persisted_values() -> None:
    assert WorkspaceRole.OWNER.value == "owner"
    assert WorkspaceRole.ADMIN.value == "admin"
    assert WorkspaceRole.MEMBER.value == "member"
    assert {role.value for role in WorkspaceRole} == {"owner", "admin", "member"}


def test_workspace_permissions_have_only_the_supported_values() -> None:
    assert {permission.value for permission in WorkspacePermission} == {
        "workflow_read",
        "workflow_create",
        "workflow_edit",
        "workflow_delete",
        "workflow_run",
        "run_read",
        "approval_decide",
        "member_manage",
        "workspace_manage",
    }
