"""Static, pure-Python Workspace role-to-permission policy."""

from types import MappingProxyType

from app.services.workspace.domain import WorkspacePermission, WorkspaceRole

_MEMBER_PERMISSIONS = frozenset(
    {
        WorkspacePermission.WORKFLOW_READ,
        WorkspacePermission.WORKFLOW_CREATE,
        WorkspacePermission.WORKFLOW_EDIT,
        WorkspacePermission.WORKFLOW_RUN,
        WorkspacePermission.RUN_READ,
    }
)
_ADMIN_PERMISSIONS = _MEMBER_PERMISSIONS | frozenset(
    {
        WorkspacePermission.WORKFLOW_DELETE,
        WorkspacePermission.APPROVAL_DECIDE,
        WorkspacePermission.MEMBER_MANAGE,
    }
)
_ROLE_PERMISSIONS = MappingProxyType(
    {
        WorkspaceRole.MEMBER: _MEMBER_PERMISSIONS,
        WorkspaceRole.ADMIN: _ADMIN_PERMISSIONS,
        WorkspaceRole.OWNER: frozenset(WorkspacePermission),
    }
)


def permissions_for_role(role: WorkspaceRole) -> frozenset[WorkspacePermission]:
    """Return the immutable set of permissions granted to a workspace role."""
    return _ROLE_PERMISSIONS[role]


def has_workspace_permission(role: WorkspaceRole, permission: WorkspacePermission) -> bool:
    """Return whether a role has one exact workspace permission."""
    return permission in permissions_for_role(role)
