"""Regression tests for conversation message ownership authorization."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_conversation_service, get_current_user, get_db_session, get_redis
from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.main import app
from app.schemas.conversation import MessageCreate, MessageRead


class MockUser:
    def __init__(self, user_id: UUID, *, is_admin: bool = False):
        self.id = user_id
        self.is_admin = is_admin

    def has_role(self, role: object) -> bool:
        return self.is_admin


class MessageAuthorizationService:
    """Small service double that enforces the route's documented ownership contract."""

    def __init__(self, owner_id: UUID):
        self.owner_id = owner_id
        self.conversation_id = uuid4()
        self.created_messages: list[MessageRead] = []
        self.read_user_ids: list[UUID | None] = []
        self.write_user_ids: list[UUID | None] = []

    def _ensure_known_and_readable(self, conversation_id: UUID, user_id: UUID | None) -> None:
        if conversation_id != self.conversation_id or user_id not in {self.owner_id, None}:
            raise NotFoundError(message="Conversation not found")

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID | None = None,
        **_: object,
    ) -> tuple[list[MessageRead], int]:
        self.read_user_ids.append(user_id)
        self._ensure_known_and_readable(conversation_id, user_id)
        return [], 0

    async def add_message(
        self,
        conversation_id: UUID,
        data: MessageCreate,
        user_id: UUID | None = None,
    ) -> MessageRead:
        self.write_user_ids.append(user_id)
        if conversation_id != self.conversation_id or user_id != self.owner_id:
            raise NotFoundError(message="Conversation not found")
        message = MessageRead(
            id=uuid4(),
            conversation_id=conversation_id,
            role=data.role,
            content=data.content,
            created_at=datetime.now(UTC),
        )
        self.created_messages.append(message)
        return message


@pytest.fixture
async def conversation_authorization_client(mock_redis: RedisClient, mock_db_session):
    owner = MockUser(uuid4())
    other = MockUser(uuid4())
    admin = MockUser(uuid4(), is_admin=True)
    current_user = [owner]
    service = MessageAuthorizationService(owner.id)

    app.dependency_overrides[get_current_user] = lambda: current_user[0]
    app.dependency_overrides[get_conversation_service] = lambda: service
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, service, owner, other, admin, current_user

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_cross_user_get_and_post_messages_return_not_found(
    conversation_authorization_client,
):
    client, service, _, other, _, current_user = conversation_authorization_client
    current_user[0] = other
    url = f"{settings.API_V1_STR}/conversations/{service.conversation_id}/messages"

    get_response = await client.get(url)
    post_response = await client.post(url, json={"role": "user", "content": "unauthorized"})

    assert get_response.status_code == 404
    assert post_response.status_code == 404
    assert (
        get_response.json()["error"]["message"]
        == post_response.json()["error"]["message"]
        == "Conversation not found"
    )
    assert service.created_messages == []


@pytest.mark.anyio
async def test_unknown_and_cross_user_conversations_are_indistinguishable(
    conversation_authorization_client,
):
    client, service, _, other, _, current_user = conversation_authorization_client
    current_user[0] = other

    other_response = await client.get(
        f"{settings.API_V1_STR}/conversations/{service.conversation_id}/messages"
    )
    missing_response = await client.get(f"{settings.API_V1_STR}/conversations/{uuid4()}/messages")

    assert other_response.status_code == missing_response.status_code == 404
    assert (
        other_response.json()["error"]["message"]
        == missing_response.json()["error"]["message"]
        == "Conversation not found"
    )


@pytest.mark.anyio
async def test_owner_can_read_and_write_messages(conversation_authorization_client):
    client, service, owner, _, _, current_user = conversation_authorization_client
    current_user[0] = owner
    url = f"{settings.API_V1_STR}/conversations/{service.conversation_id}/messages"

    get_response = await client.get(url)
    post_response = await client.post(url, json={"role": "user", "content": "owned"})

    assert get_response.status_code == 200
    assert post_response.status_code == 201
    assert service.read_user_ids == [owner.id]
    assert service.write_user_ids == [owner.id]
    assert len(service.created_messages) == 1


@pytest.mark.anyio
async def test_admin_can_read_but_cannot_write_other_users_messages(
    conversation_authorization_client,
):
    client, service, _, _, admin, current_user = conversation_authorization_client
    current_user[0] = admin
    url = f"{settings.API_V1_STR}/conversations/{service.conversation_id}/messages"

    get_response = await client.get(url)
    post_response = await client.post(url, json={"role": "user", "content": "admin injection"})

    assert get_response.status_code == 200
    assert post_response.status_code == 404
    assert service.read_user_ids == [None]
    assert service.write_user_ids == [admin.id]
    assert service.created_messages == []
