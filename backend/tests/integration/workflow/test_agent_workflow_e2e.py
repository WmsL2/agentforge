"""Opt-in PostgreSQL E2E coverage for AGENT workflow execution."""

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session, get_langgraph_agent_runner
from app.db.models.user import User, UserRole
from app.db.models.workflow.definition.model import Workflow
from app.db.models.workflow.run.model import WorkflowRun
from app.main import app
from app.services.agent_runtime import AgentExecutionRequest, AgentExecutionResult


class FakeAgentRunner:
    """Offline AgentRunner replacement for the production dependency graph."""

    def __init__(self) -> None:
        self.requests: list[AgentExecutionRequest] = []

    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.requests.append(request)
        return AgentExecutionResult(output={"answer": "postgres-e2e"})


@pytest.mark.anyio
async def test_agent_workflow_executes_and_persists_through_postgres(
    postgres_session: AsyncSession,
) -> None:
    user = User(
        id=uuid4(),
        email=f"agent-workflow-e2e-{uuid4()}@example.test",
        role=UserRole.USER.value,
    )
    postgres_session.add(user)
    await postgres_session.flush()

    async def override_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield postgres_session

    runner = FakeAgentRunner()
    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_langgraph_agent_runner] = lambda: runner
    payload = {
        "name": "PostgreSQL AGENT workflow",
        "definition": {
            "entry_node_id": "start",
            "nodes": [
                {"id": "start", "kind": "start"},
                {
                    "id": "agent",
                    "kind": "agent",
                    "config": {
                        "runner": "langgraph",
                        "instruction": "Analyze the workflow input.",
                    },
                },
                {"id": "end", "kind": "end"},
            ],
            "edges": [
                {"id": "start-agent", "source": "start", "target": "agent"},
                {"id": "agent-end", "source": "agent", "target": "end"},
            ],
        },
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create_response = await client.post("/api/v1/workflows", json=payload)
            assert create_response.status_code == 201
            workflow_id = UUID(create_response.json()["id"])

            workflow = await postgres_session.scalar(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            assert workflow is not None
            assert workflow.user_id == user.id
            assert workflow.revision == 1
            assert isinstance(workflow.definition, dict)
            agent_node = next(
                node for node in workflow.definition["nodes"] if node["id"] == "agent"
            )
            assert agent_node["kind"] == "agent"
            assert agent_node["config"]["runner"] == "langgraph"

            execute_response = await client.post(
                f"/api/v1/workflows/{workflow_id}/runs",
                json={"input": {"question": "What is the answer?"}},
            )
            assert execute_response.status_code == 201
            run_body = execute_response.json()
            run_id = UUID(run_body["id"])
            postgres_session.info["e2e_workflow_id"] = workflow.id
            postgres_session.info["e2e_run_id"] = run_id

            assert run_body["status"] == "completed"
            assert len(runner.requests) == 1
            assert runner.requests[0].instruction == "Analyze the workflow input."
            assert runner.requests[0].input == {"start": {"question": "What is the answer?"}}

            workflow_run = await postgres_session.scalar(
                select(WorkflowRun).where(WorkflowRun.id == run_id)
            )
            assert workflow_run is not None
            assert workflow_run.workflow_id == workflow.id
            assert workflow_run.workflow_revision == 1
            assert workflow_run.status == "completed"
            assert workflow_run.input == {"question": "What is the answer?"}
            assert workflow_run.node_outputs["agent"] == {"answer": "postgres-e2e"}
            assert workflow_run.node_outputs["end"] == {"agent": {"answer": "postgres-e2e"}}
            assert workflow_run.output == {"end": {"agent": {"answer": "postgres-e2e"}}}
            assert workflow_run.error is None
            assert workflow_run.started_at is not None
            assert workflow_run.finished_at is not None
            assert workflow_run.definition_snapshot["schema_version"] == 1
            assert workflow_run.definition_snapshot["entry_node_id"] == "start"
            assert workflow_run.definition_snapshot["nodes"]
            assert workflow_run.definition_snapshot["edges"]
            snapshot_agent = next(
                node for node in workflow_run.definition_snapshot["nodes"] if node["id"] == "agent"
            )
            assert snapshot_agent["kind"] == "agent"
            assert snapshot_agent["config"]["runner"] == "langgraph"

            get_response = await client.get(f"/api/v1/workflows/{workflow_id}/runs/{run_id}")
            assert get_response.status_code == 200
            assert get_response.json()["status"] == "completed"
            assert get_response.json()["node_outputs"] == run_body["node_outputs"]
            assert get_response.json()["output"] == run_body["output"]

            list_response = await client.get(f"/api/v1/workflows/{workflow_id}/runs")
            assert list_response.status_code == 200
            assert list_response.json()["total"] >= 1
            assert str(run_id) in {item["id"] for item in list_response.json()["items"]}
    finally:
        app.dependency_overrides.clear()
