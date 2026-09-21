"""Tests for pure workspace domain types."""

from app.services.workspace import WorkspaceRole


def test_workspace_roles_have_only_the_persisted_values() -> None:
    assert WorkspaceRole.OWNER.value == "owner"
    assert WorkspaceRole.ADMIN.value == "admin"
    assert WorkspaceRole.MEMBER.value == "member"
    assert {role.value for role in WorkspaceRole} == {"owner", "admin", "member"}
