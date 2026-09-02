"""Opt-in real PostgreSQL verification for the Workflow HTTP round trip."""

import os
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun
from app.db.session import async_session_maker, engine
from app.main import app

VERIFY_DATABASE = "agentforge_v02_verify"
RUN_INTEGRATION = os.getenv("AGENTFORGE_RUN_POSTGRES_INTEGRATION") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="set AGENTFORGE_RUN_POSTGRES_INTEGRATION=1 to run real PostgreSQL integration tests",
)


def require_verification_database() -> None:
    """Refuse destructive test cleanup outside this Atomic's disposable database."""
    if settings.POSTGRES_DB != VERIFY_DATABASE:
        pytest.fail(
            "PostgreSQL integration requires "
            f"POSTGRES_DB={VERIFY_DATABASE!r}; got {settings.POSTGRES_DB!r}."
        )


async def assert_postgres_available() -> None:
    """Fail explicitly rather than silently falling back to mocked persistence."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.fail(
            "PostgreSQL integration was requested but the verification database is unavailable: "
            f"{exc}"
        )


def workflow_definition() -> dict[str, object]:
    return {
        "entry_node_id": "start",
        "nodes": [
            {"id": "start", "kind": "start"},
            {"id": "value", "kind": "value", "config": {"value": 42}},
            {"id": "end", "kind": "end"},
        ],
        "edges": [
            {"id": "start-value", "source": "start", "target": "value"},
            {"id": "value-end", "source": "value", "target": "end"},
        ],
    }


@pytest.mark.anyio
async def test_workflow_http_round_trip_uses_real_postgresql() -> None:
    require_verification_database()
    await assert_postgres_available()

    user_id = uuid4()
    user = User(
        id=user_id,
        email=f"workflow-postgres-{user_id.hex}@example.invalid",
        hashed_password=None,
    )
    user_created = False
    try:
        async with async_session_maker() as session:
            session.add(user)
            await session.commit()
            user_created = True

        app.dependency_overrides[get_current_user] = lambda: user
        definition = workflow_definition()
        run_input = {"request": "postgres-roundtrip"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created_workflow = await client.post(
                "/api/v1/workflows",
                json={"name": "PostgreSQL round trip", "definition": definition},
            )
            assert created_workflow.status_code == 201
            created_workflow_body = created_workflow.json()
            workflow_id = created_workflow_body["id"]
            assert created_workflow_body["revision"] == 1

            created_run = await client.post(
                f"/api/v1/workflows/{workflow_id}/runs",
                json={"input": run_input},
            )
            assert created_run.status_code == 201
            created_run_body = created_run.json()
            run_id = created_run_body["id"]
            assert created_run_body["status"] == "completed"
            assert created_run_body["workflow_id"] == workflow_id
            assert created_run_body["workflow_revision"] == 1
            assert created_run_body["definition_snapshot"] == created_workflow_body["definition"]
            assert created_run_body["input"] == run_input
            assert created_run_body["node_outputs"]["start"] == run_input
            assert created_run_body["node_outputs"]["value"] == 42
            assert created_run_body["node_outputs"]["end"] == {"value": 42}
            assert created_run_body["output"] == {"end": {"value": 42}}
            assert created_run_body["started_at"] is not None
            assert created_run_body["finished_at"] is not None
            assert created_run_body["error"] is None

            run_detail = await client.get(f"/api/v1/workflows/{workflow_id}/runs/{run_id}")
            assert run_detail.status_code == 200
            assert run_detail.json()["id"] == run_id
            assert run_detail.json()["status"] == "completed"

            run_list = await client.get(f"/api/v1/workflows/{workflow_id}/runs")
            assert run_list.status_code == 200
            assert run_list.json()["total"] >= 1
            assert any(item["id"] == run_id for item in run_list.json()["items"])

        async with async_session_maker() as session:
            stored_workflow = await session.get(Workflow, UUID(workflow_id))
            stored_run = await session.get(WorkflowRun, UUID(run_id))
            assert stored_workflow is not None
            assert stored_run is not None
            assert str(stored_workflow.id) == workflow_id
            assert str(stored_run.workflow_id) == workflow_id
            assert stored_run.workflow_revision == 1
            assert stored_run.status == "completed"
            assert stored_run.definition_snapshot == stored_workflow.definition
            assert stored_run.input == run_input
            assert stored_run.node_outputs["start"] == run_input
            assert stored_run.node_outputs["value"] == 42
            assert stored_run.node_outputs["end"] == {"value": 42}
            assert stored_run.output == {"end": {"value": 42}}
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        if user_created:
            async with async_session_maker() as session:
                persisted_user = await session.get(User, user_id)
                if persisted_user is not None:
                    await session.delete(persisted_user)
                    await session.commit()
