"""Service-level ownership regressions for message access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.schemas.conversation import MessageCreate
from app.services.conversation import ConversationService


@pytest.mark.anyio
async def test_list_messages_rejects_non_owner_before_loading_messages():
    conversation_id = uuid4()
    owner_id = uuid4()
    other_id = uuid4()
    service = ConversationService(AsyncMock())
    conversation = SimpleNamespace(id=conversation_id, user_id=owner_id)

    with patch("app.services.conversation.conversation_repo") as repository:
        repository.get_conversation_by_id = AsyncMock(return_value=conversation)
        repository.get_messages_by_conversation = AsyncMock()

        with pytest.raises(NotFoundError):
            await service.list_messages(conversation_id, user_id=other_id)

        repository.get_messages_by_conversation.assert_not_called()


@pytest.mark.anyio
async def test_add_message_rejects_non_owner_before_creating_message():
    conversation_id = uuid4()
    owner_id = uuid4()
    other_id = uuid4()
    service = ConversationService(AsyncMock())
    conversation = SimpleNamespace(id=conversation_id, user_id=owner_id)

    with patch("app.services.conversation.conversation_repo") as repository:
        repository.get_conversation_by_id = AsyncMock(return_value=conversation)
        repository.create_message = AsyncMock()

        with pytest.raises(NotFoundError):
            await service.add_message(
                conversation_id,
                MessageCreate(role="user", content="unauthorized"),
                user_id=other_id,
            )

        repository.create_message.assert_not_called()
