"""Workflow route smoke tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_workflow_service
from app.main import app
from app.services.workflow.application.definition.service import WorkflowService


def workflow_row(workspace_id):
    return SimpleNamespace(id=uuid4(), user_id=uuid4(), workspace_id=workspace_id, name="Workflow", description=None, definition={"entry_node_id": "start", "nodes": [], "edges": []}, revision=1, created_at=datetime.now(UTC), updated_at=None)


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


@pytest.mark.anyio
async def test_validate_route_accepts_valid_agent_graph(mock_db_session):
    user = type("User", (), {"id": "00000000-0000-0000-0000-000000000001"})()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_service] = lambda: WorkflowService(mock_db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/workflows/validate",
                json={
                    "entry_node_id": "start",
                    "nodes": [
                        {"id": "start", "kind": "start"},
                        {
                            "id": "agent",
                            "kind": "agent",
                            "config": {"runner": "langgraph", "instruction": "Analyze input."},
                        },
                        {"id": "end", "kind": "end"},
                    ],
                    "edges": [
                        {"id": "start-agent", "source": "start", "target": "agent"},
                        {"id": "agent-end", "source": "agent", "target": "end"},
                    ],
                },
            )
        assert response.status_code == 200
        assert response.json() == {"is_valid": True, "issues": []}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_validate_route_reports_invalid_agent_config(mock_db_session):
    user = type("User", (), {"id": "00000000-0000-0000-0000-000000000001"})()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_service] = lambda: WorkflowService(mock_db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/workflows/validate",
                json={
                    "entry_node_id": "start",
                    "nodes": [
                        {"id": "start", "kind": "start"},
                        {
                            "id": "agent",
                            "kind": "agent",
                            "config": {"runner": "native", "instruction": "Run"},
                        },
                        {"id": "end", "kind": "end"},
                    ],
                    "edges": [
                        {"id": "start-agent", "source": "start", "target": "agent"},
                        {"id": "agent-end", "source": "agent", "target": "end"},
                    ],
                },
            )
        assert response.status_code == 200
        assert response.json()["is_valid"] is False
        assert response.json()["issues"] == [
            {
                "code": "agent_runner_invalid",
                "message": "AGENT config field 'runner' must be exactly 'langgraph'.",
                "node_id": "agent",
                "edge_id": None,
            }
        ]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_workspace_query_contract_for_list_create_and_missing_query() -> None:
    user = SimpleNamespace(id=uuid4())
    workspace_id = uuid4()
    row = workflow_row(workspace_id)
    service = SimpleNamespace(
        list_workflows=AsyncMock(return_value=([row], 1)),
        create_workflow=AsyncMock(return_value=row),
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/v1/workflows")).status_code == 422
            assert (await client.post("/api/v1/workflows", json={"name": "W", "definition": {"entry_node_id": "start", "nodes": [], "edges": []}})).status_code == 422
            assert (await client.get(f"/api/v1/workflows?workspace_id={workspace_id}&skip=0&limit=50")).status_code == 200
            assert (await client.post(f"/api/v1/workflows?workspace_id={workspace_id}", json={"name": "W", "definition": {"entry_node_id": "start", "nodes": [], "edges": []}})).status_code == 201
    finally:
        app.dependency_overrides.clear()
    service.list_workflows.assert_awaited_once_with(workspace_id, user.id, 0, 50)
    assert service.create_workflow.await_args.args[:2] == (workspace_id, user.id)
