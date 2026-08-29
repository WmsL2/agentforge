"""Schemas for admin conversation views."""

from datetime import datetime
from uuid import UUID

from app.schemas.base import BaseSchema


class AdminConversationRead(BaseSchema):
    """Admin view of a conversation, including owner email."""

    id: UUID
    user_id: UUID | None = None
    title: str | None = None
    is_archived: bool = False
    message_count: int = 0
    user_email: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class AdminConversationList(BaseSchema):
    """Paginated list of conversations for admins."""

    items: list[AdminConversationRead]
    total: int
