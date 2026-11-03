"""Pure workspace domain types."""

from enum import Enum


class WorkspaceRole(str, Enum):  # noqa: UP042
    """A member's persisted workspace role."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class WorkspacePermission(str, Enum):  # noqa: UP042
    """A permission evaluated only within a workspace membership."""

    WORKFLOW_READ = "workflow_read"
    WORKFLOW_CREATE = "workflow_create"
    WORKFLOW_EDIT = "workflow_edit"
    WORKFLOW_DELETE = "workflow_delete"
    WORKFLOW_RUN = "workflow_run"
    RUN_READ = "run_read"
    APPROVAL_DECIDE = "approval_decide"
    KNOWLEDGE_READ = "knowledge_read"
    KNOWLEDGE_CREATE = "knowledge_create"
    KNOWLEDGE_EDIT = "knowledge_edit"
    KNOWLEDGE_DELETE = "knowledge_delete"
    MEMBER_MANAGE = "member_manage"
    WORKSPACE_MANAGE = "workspace_manage"
