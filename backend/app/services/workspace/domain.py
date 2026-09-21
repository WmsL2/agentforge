"""Pure workspace domain types."""

from enum import Enum


class WorkspaceRole(str, Enum):  # noqa: UP042
    """A member's persisted workspace role."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
