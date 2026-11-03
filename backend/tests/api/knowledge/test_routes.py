"""HTTP routing tests for workspace-scoped knowledge bases."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_knowledge_base_service
from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.main import app


def knowledge_base(workspace_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        name="Research",
        description=None,
        created_by_user_id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=None,
    )


@pytest.mark.anyio
async def test_routes_are_registered_forward_actor_and_return_crud_statuses() -> None:
    user = SimpleNamespace(id=uuid4())
    workspace_id = uuid4()
    row = knowledge_base(workspace_id)
    service = SimpleNamespace(
        create_knowledge_base=AsyncMock(return_value=row),
        list_knowledge_bases=AsyncMock(return_value=([row], 1)),
        get_knowledge_base=AsyncMock(return_value=row),
        update_knowledge_base=AsyncMock(return_value=row),
        delete_knowledge_base=AsyncMock(),
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_base_service] = lambda: service
    base = f"/api/v1/workspaces/{workspace_id}/knowledge-bases"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(base, json={"name": "Research"})
            listed = await client.get(base, params={"skip": 2, "limit": 10})
            fetched = await client.get(f"{base}/{row.id}")
            updated = await client.patch(f"{base}/{row.id}", json={"description": None})
            deleted = await client.delete(f"{base}/{row.id}")
    finally:
        app.dependency_overrides.clear()

    assert [created.status_code, listed.status_code, fetched.status_code] == [201, 200, 200]
    assert [updated.status_code, deleted.status_code] == [200, 204]
    assert set(created.json()) == {
        "id",
        "workspace_id",
        "name",
        "description",
        "created_by_user_id",
        "created_at",
        "updated_at",
    }
    assert listed.json()["total"] == 1
    service.create_knowledge_base.assert_awaited_once_with(workspace_id, user.id, ANY)
    service.list_knowledge_bases.assert_awaited_once_with(workspace_id, user.id, skip=2, limit=10)
    service.get_knowledge_base.assert_awaited_once_with(workspace_id, row.id, user.id)
    service.update_knowledge_base.assert_awaited_once_with(workspace_id, row.id, user.id, ANY)
    service.delete_knowledge_base.assert_awaited_once_with(workspace_id, row.id, user.id)


@pytest.mark.anyio
async def test_unauthenticated_request_is_401_and_does_not_call_service() -> None:
    service = SimpleNamespace(list_knowledge_bases=AsyncMock())
    app.dependency_overrides[get_knowledge_base_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/workspaces/{uuid4()}/knowledge-bases")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401
    service.list_knowledge_bases.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "payload"),
    [
        ("post", {"name": "   "}),
        ("patch", {"name": None}),
    ],
)
async def test_invalid_names_return_422_without_calling_service(method: str, payload: dict) -> None:
    user = SimpleNamespace(id=uuid4())
    service = SimpleNamespace(create_knowledge_base=AsyncMock(), update_knowledge_base=AsyncMock())
    workspace_id, knowledge_base_id = uuid4(), uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_base_service] = lambda: service
    url = f"/api/v1/workspaces/{workspace_id}/knowledge-bases"
    if method == "patch":
        url += f"/{knowledge_base_id}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await getattr(client, method)(url, json=payload)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    service.create_knowledge_base.assert_not_awaited()
    service.update_knowledge_base.assert_not_awaited()


@pytest.mark.anyio
async def test_pagination_limit_is_bounded() -> None:
    user = SimpleNamespace(id=uuid4())
    service = SimpleNamespace(list_knowledge_bases=AsyncMock())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_base_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/workspaces/{uuid4()}/knowledge-bases?limit=101")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    service.list_knowledge_bases.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (AuthorizationError(message="denied"), 403),
        (NotFoundError(message="missing"), 404),
        (AlreadyExistsError(message="duplicate"), 409),
    ],
)
async def test_application_errors_keep_their_http_status(
    error: Exception, status_code: int
) -> None:
    user = SimpleNamespace(id=uuid4())
    service = SimpleNamespace(create_knowledge_base=AsyncMock(side_effect=error))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_base_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workspaces/{uuid4()}/knowledge-bases",
                json={"name": "Research"},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status_code
