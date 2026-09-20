"""Workflow-run route tests using service dependency overrides."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_workflow_run_service
from app.main import app


def run_row(status="completed"):
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        workflow_id=uuid4(),
        workflow_revision=1,
        definition_snapshot={
            "entry_node_id": "start",
            "nodes": [],
            "edges": [],
            "schema_version": 1,
            "metadata": {},
        },
        status=status,
        input={},
        node_outputs={},
        output={} if status == "completed" else None,
        error=None
        if status == "completed"
        else {"code": "node_execution_failed", "message": "boom", "node_id": "end"},
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=None,
    )


def step_row():
    started_at = datetime(2026, 9, 1, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        sequence=2,
        node_id="agent",
        node_kind="agent",
        status="completed",
        input={"request": "status"},
        output={"answer": "ok"},
        error=None,
        metadata_={"model": "offline"},
        started_at=started_at,
        finished_at=started_at.replace(second=1, microsecond=500000),
    )


def trace_event_row():
    return SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        step_id=None,
        kind="approval_approved",
        payload={"node_id": "approval"},
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


@pytest.mark.anyio
async def test_execute_and_list_routes_use_authenticated_run_service():
    user = SimpleNamespace(id=uuid4())
    row = run_row()

    class RunService:
        async def execute_workflow(self, *_):
            return row

        async def list_workflow_runs(self, *_):
            return [row], 1

    service = RunService()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_run_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workflows/{row.workflow_id}/runs", json={"input": {}}
            )
            listed = await client.get(f"/api/v1/workflows/{row.workflow_id}/runs?skip=0&limit=50")
        assert response.status_code == 201
        assert response.json()["status"] == "completed"
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_failed_run_returns_created_with_structured_error():
    user = SimpleNamespace(id=uuid4())
    row = run_row("failed")

    class RunService:
        async def execute_workflow(self, *_):
            return row

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_run_service] = RunService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/workflows/{row.workflow_id}/runs", json={})
        assert response.status_code == 201
        assert response.json()["status"] == "failed"
        assert response.json()["error"]["code"] == "node_execution_failed"
        assert response.json()["error"]["node_id"] == "end"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_detail_route_passes_parent_run_and_current_user_to_service():
    user = SimpleNamespace(id=uuid4())
    row = run_row()
    calls = []

    class RunService:
        async def get_workflow_run(self, workflow_id, run_id, user_id):
            calls.append((workflow_id, run_id, user_id))
            return row

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_run_service] = RunService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/workflows/{row.workflow_id}/runs/{row.id}")
        assert response.status_code == 200
        assert response.json()["id"] == str(row.id)
        assert calls == [(row.workflow_id, row.id, user.id)]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_steps_route_returns_read_model_and_passes_authenticated_identity():
    user = SimpleNamespace(id=uuid4())
    row = step_row()
    workflow_id = uuid4()
    calls = []

    class RunService:
        async def list_workflow_run_steps(self, workflow_id, run_id, user_id):
            calls.append((workflow_id, run_id, user_id))
            return [row]

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_run_service] = RunService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/workflows/{workflow_id}/runs/{row.run_id}/steps")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls == [(workflow_id, row.run_id, user.id)]
    item = response.json()[0]
    assert item["sequence"] == 2
    assert item["node_id"] == "agent"
    assert item["node_kind"] == "agent"
    assert item["status"] == "completed"
    assert item["metadata"] == {"model": "offline"}
    assert item["duration_ms"] == 1500.0
    assert "metadata_" not in item


@pytest.mark.anyio
async def test_trace_route_returns_run_level_event_and_passes_authenticated_identity():
    user = SimpleNamespace(id=uuid4())
    row = trace_event_row()
    workflow_id = uuid4()
    calls = []

    class RunService:
        async def list_workflow_trace_events(self, workflow_id, run_id, user_id):
            calls.append((workflow_id, run_id, user_id))
            return [row]

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_run_service] = RunService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/workflows/{workflow_id}/runs/{row.run_id}/trace")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls == [(workflow_id, row.run_id, user.id)]
    item = response.json()[0]
    assert item["kind"] == "approval_approved"
    assert item["step_id"] is None
    assert item["payload"] == {"node_id": "approval"}
    assert item["created_at"] == "2026-09-01T00:00:00+00:00"


@pytest.mark.anyio
@pytest.mark.parametrize("path_suffix", ["steps", "trace"])
async def test_observability_routes_return_empty_array_for_a_valid_run(path_suffix):
    user = SimpleNamespace(id=uuid4())
    workflow_id, run_id = uuid4(), uuid4()

    class RunService:
        async def list_workflow_run_steps(self, *_):
            return []

        async def list_workflow_trace_events(self, *_):
            return []

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_run_service] = RunService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/workflows/{workflow_id}/runs/{run_id}/{path_suffix}"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []
