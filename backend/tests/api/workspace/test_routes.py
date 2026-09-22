"""HTTP routing tests for Workspace service composition."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_workspace_service
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
)
from app.main import app
from app.services.workspace.domain import WorkspaceRole


def workspace() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name="Team",
        created_by_user_id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=None,
    )


def member(workspace_id, user_id) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_id=workspace_id,
        user_id=user_id,
        role=WorkspaceRole.MEMBER.value,
        created_at=datetime.now(UTC),
        updated_at=None,
    )


@pytest.mark.anyio
async def test_workspace_routes_forward_current_user_and_return_expected_statuses() -> None:
    user = SimpleNamespace(id=uuid4())
    row = workspace()
    target_user_id = uuid4()
    service = SimpleNamespace(
        create_workspace=AsyncMock(return_value=row),
        list_workspaces=AsyncMock(return_value=[row]),
        get_workspace=AsyncMock(return_value=row),
        update_workspace=AsyncMock(return_value=row),
        delete_workspace=AsyncMock(),
        list_members=AsyncMock(return_value=[member(row.id, target_user_id)]),
        add_member=AsyncMock(return_value=member(row.id, target_user_id)),
        update_member=AsyncMock(return_value=member(row.id, target_user_id)),
        delete_member=AsyncMock(),
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workspace_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/api/v1/workspaces", json={"name": "Team"})).status_code == 201
            assert (await client.get("/api/v1/workspaces")).status_code == 200
            assert (await client.get(f"/api/v1/workspaces/{row.id}")).status_code == 200
            assert (await client.patch(f"/api/v1/workspaces/{row.id}", json={"name": "Renamed"})).status_code == 200
            assert (await client.delete(f"/api/v1/workspaces/{row.id}")).status_code == 204
            assert (await client.get(f"/api/v1/workspaces/{row.id}/members")).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/workspaces/{row.id}/members",
                    json={"user_id": str(target_user_id), "role": "member"},
                )
            ).status_code == 201
            assert (
                await client.patch(
                    f"/api/v1/workspaces/{row.id}/members/{target_user_id}", json={"role": "admin"}
                )
            ).status_code == 200
            assert (await client.delete(f"/api/v1/workspaces/{row.id}/members/{target_user_id}")).status_code == 204
    finally:
        app.dependency_overrides.clear()

    service.create_workspace.assert_awaited_once_with(user.id, ANY)
    service.list_workspaces.assert_awaited_once_with(user.id)
    service.get_workspace.assert_awaited_once_with(row.id, user.id)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (NotFoundError(message="missing"), 404),
        (AuthorizationError(message="denied"), 403),
        (AlreadyExistsError(message="duplicate"), 409),
        (ValidationError(message="invalid"), 422),
    ],
)
async def test_workspace_route_maps_application_errors(error: Exception, status_code: int) -> None:
    user = SimpleNamespace(id=uuid4())
    service = SimpleNamespace(list_workspaces=AsyncMock(side_effect=error))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workspace_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/workspaces")
        assert response.status_code == status_code
    finally:
        app.dependency_overrides.clear()
