"""Workflow route smoke tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_workflow_service
from app.main import app
from app.services.workflow.facade import WorkflowService


@pytest.mark.anyio
async def test_validate_route_is_not_captured_as_workflow_id(mock_db_session):
    user = type("User", (), {"id": "00000000-0000-0000-0000-000000000001"})()
    service = WorkflowService(mock_db_session)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/workflows/validate",
                json={"entry_node_id": "start", "nodes": [], "edges": []},
            )
        assert response.status_code == 200
        assert response.json()["is_valid"] is False
        assert response.json()["issues"][0]["code"] == "empty_workflow"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_validate_valid_graph_returns_200_and_true(mock_db_session):
    user = type("User", (), {"id": "00000000-0000-0000-0000-000000000001"})()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_service] = lambda: WorkflowService(mock_db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/workflows/validate",
                json={
                    "entry_node_id": "start",
                    "nodes": [{"id": "start", "kind": "start"}, {"id": "end", "kind": "end"}],
                    "edges": [{"id": "edge", "source": "start", "target": "end"}],
                },
            )
        assert response.status_code == 200
        assert response.json() == {"is_valid": True, "issues": []}
    finally:
        app.dependency_overrides.clear()
