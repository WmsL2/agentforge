"""Workspace domain contracts."""

from app.services.workspace.domain import WorkspacePermission, WorkspaceRole
from app.services.workspace.policy import has_workspace_permission, permissions_for_role

__all__ = [
    "WorkspaceAuthorizationService",
    "WorkspacePermission",
    "WorkspaceRole",
    "WorkspaceService",
    "has_workspace_permission",
    "permissions_for_role",
]


def __getattr__(name: str):
    """Load the database-backed authorization service without ORM import cycles."""
    if name == "WorkspaceAuthorizationService":
        from app.services.workspace.authorization import WorkspaceAuthorizationService

        return WorkspaceAuthorizationService
    if name == "WorkspaceService":
        from app.services.workspace.service import WorkspaceService

        return WorkspaceService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
