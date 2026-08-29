from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    ConversationSvc,
    CurrentAdmin,
    CurrentUser,
)
from app.db.models.user import UserRole
from app.schemas.conversation import (
    ConversationAdminList,
    ConversationCreate,
    ConversationExport,
    ConversationList,
    ConversationRead,
    ConversationReadWithMessages,
    ConversationUpdate,
    MessageCreate,
    MessageList,
    MessageRead,
)

router = APIRouter()


@router.get("/export", response_model=ConversationExport)
async def export_conversations(
    conversation_service: ConversationSvc,
    _: CurrentAdmin,
) -> Any:
    """Export all conversations with messages and tool calls (admin only)."""
    export_data = await conversation_service.export_all()
    return JSONResponse(
        content={"conversations": export_data, "total": len(export_data)},
        headers={"Content-Disposition": 'attachment; filename="conversations_export.json"'},
    )


@router.get("/admin-list", response_model=ConversationAdminList)
async def list_conversations_admin(
    conversation_service: ConversationSvc,
    _: CurrentAdmin,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    include_archived: bool = Query(True, description="Include archived conversations"),
    search: str | None = Query(None, max_length=100, description="Search by title or ID prefix"),
) -> Any:
    """List all conversations with message counts (admin only)."""
    items, total = await conversation_service.list_conversations_admin(
        skip=skip,
        limit=limit,
        include_archived=include_archived,
        search=search,
    )
    return ConversationAdminList(items=items, total=total)


@router.get("", response_model=ConversationList)
async def list_conversations(
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    skip: int = Query(0, ge=0, description="Number of conversations to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum conversations to return"),
    include_archived: bool = Query(False, description="Include archived conversations"),
) -> Any:
    """List conversations for the current user."""
    items, total = await conversation_service.list_conversations(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        include_archived=include_archived,
    )
    return ConversationList(items=items, total=total)  # ty: ignore[invalid-argument-type]


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    data: ConversationCreate | None = None,
) -> Any:
    """Create a new conversation."""
    if data is None:
        data = ConversationCreate()
    data = data.model_copy(update={"user_id": current_user.id})
    return await conversation_service.create_conversation(data)


@router.get("/{conversation_id}", response_model=ConversationReadWithMessages)
async def get_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
) -> Any:
    """Get a conversation with all its messages."""
    uid = None if current_user.has_role(UserRole.ADMIN) else current_user.id
    return await conversation_service.get_conversation(
        conversation_id,
        include_messages=True,
        user_id=uid,
    )


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: UUID,
    data: ConversationUpdate,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
) -> Any:
    """Update a conversation's title or archived status."""
    return await conversation_service.update_conversation(
        conversation_id,
        data,
        user_id=current_user.id,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
) -> None:
    """Delete a conversation and all its messages."""
    await conversation_service.delete_conversation(
        conversation_id,
        user_id=current_user.id,
    )


@router.post(
    "/{conversation_id}/archive",
    response_model=ConversationRead,
)
async def archive_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
) -> Any:
    """Archive a conversation.

    Archived conversations are hidden from the default list view.
    """
    return await conversation_service.archive_conversation(
        conversation_id,
        user_id=current_user.id,
    )


@router.get("/{conversation_id}/messages", response_model=MessageList)
async def list_messages(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> Any:
    """List messages in a conversation."""
    items, total = await conversation_service.list_messages(
        conversation_id,
        skip=skip,
        limit=limit,
        include_tool_calls=True,
    )
    return MessageList(items=items, total=total)  # ty: ignore[invalid-argument-type]


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_message(
    conversation_id: UUID,
    data: MessageCreate,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
) -> Any:
    """Add a message to a conversation."""
    return await conversation_service.add_message(conversation_id, data)
