"""Opt-in PostgreSQL E2E coverage for an approval-paused workflow."""

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session, get_langgraph_agent_runner
from app.db.models.user import User, UserRole
from app.db.models.workflow import ApprovalRequest, Workflow, WorkflowCheckpoint, WorkflowRun
from app.main import app


class NoopAgentRunner:
    """Fail if an approval-only workflow unexpectedly reaches an AGENT node."""

    async def run(self, request):
        raise AssertionError("Approval-only workflow must not execute an AGENT node.")


@pytest.mark.anyio
async def test_approval_workflow_approve_resumes_and_completes_through_postgres(
    postgres_session: AsyncSession,
) -> None:
    user = User(id=uuid4(), email=f"approval-e2e-{uuid4()}@example.test", role=UserRole.USER.value)
    postgres_session.add(user)
    await postgres_session.flush()

    async def override_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield postgres_session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_langgraph_agent_runner] = lambda: NoopAgentRunner()
    payload = {
        "name": "PostgreSQL approval workflow",
        "definition": {
            "entry_node_id": "start",
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "approval", "kind": "approval", "config": {"prompt": "Continue?"}},
                {"id": "end", "kind": "end"},
            ],
            "edges": [
                {"id": "start-approval", "source": "start", "target": "approval"},
                {"id": "approval-end", "source": "approval", "target": "end"},
            ],
        },
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/v1/workflows", json=payload)
            assert created.status_code == 201
            workflow_id = UUID(created.json()["id"])
            executed = await client.post(
                f"/api/v1/workflows/{workflow_id}/runs", json={"input": {}}
            )
            assert executed.status_code == 201
            run_id = UUID(executed.json()["id"])
            postgres_session.info["e2e_workflow_id"] = workflow_id
            postgres_session.info["e2e_run_id"] = run_id

            assert executed.json()["status"] == "paused"
            pending = await client.get(
                f"/api/v1/workflows/{workflow_id}/runs/{run_id}/approvals/pending"
            )
            assert pending.status_code == 200
            approval_id = UUID(pending.json()["id"])
            decided = await client.post(
                f"/api/v1/workflows/{workflow_id}/runs/{run_id}/approvals/{approval_id}/approve",
                json={"note": "Looks good"},
            )
            assert decided.status_code == 200
            assert decided.json()["status"] == "approved"

        run = await postgres_session.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id))
        approval = await postgres_session.scalar(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
        )
        checkpoints = list(
            (
                await postgres_session.scalars(
                    select(WorkflowCheckpoint)
                    .where(WorkflowCheckpoint.run_id == run_id)
                    .order_by(WorkflowCheckpoint.sequence)
                )
            ).all()
        )
        workflow = await postgres_session.scalar(select(Workflow).where(Workflow.id == workflow_id))
        assert workflow is not None
        assert run is not None and run.status == "completed"
        assert (
            approval is not None
            and approval.status == "approved"
            and approval.decision_note == "Looks good"
        )
        assert run.node_outputs["approval"]["decision"] == "approved"
        assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 2, 3, 4]
        assert checkpoints[1].pending_node_id == "approval"
        assert checkpoints[1].interrupt == {
            "type": "approval_required",
            "payload": {"node_id": "approval", "prompt": "Continue?"},
        }
        assert "approval" in checkpoints[2].completed_node_ids
        assert checkpoints[2].pending_node_id is None
        assert checkpoints[2].interrupt is None
        assert checkpoints[2].node_outputs["approval"]["decision"] == "approved"
        assert "end" in checkpoints[3].completed_node_ids
        assert checkpoints[3].pending_node_id is None
        assert checkpoints[3].interrupt is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_approval_workflow_reject_cancels_without_resolution_checkpoint_through_postgres(
    postgres_session: AsyncSession,
) -> None:
    user = User(
        id=uuid4(), email=f"approval-reject-e2e-{uuid4()}@example.test", role=UserRole.USER.value
    )
    postgres_session.add(user)
    await postgres_session.flush()

    async def override_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield postgres_session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_langgraph_agent_runner] = lambda: NoopAgentRunner()
    payload = {
        "name": "PostgreSQL rejection workflow",
        "definition": {
            "entry_node_id": "start",
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "approval", "kind": "approval", "config": {"prompt": "Continue?"}},
                {"id": "end", "kind": "end"},
            ],
            "edges": [
                {"id": "start-approval", "source": "start", "target": "approval"},
                {"id": "approval-end", "source": "approval", "target": "end"},
            ],
        },
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/v1/workflows", json=payload)
            assert created.status_code == 201
            workflow_id = UUID(created.json()["id"])
            executed = await client.post(
                f"/api/v1/workflows/{workflow_id}/runs", json={"input": {}}
            )
            assert executed.status_code == 201
            run_id = UUID(executed.json()["id"])
            assert executed.json()["status"] == "paused"
            pending = await client.get(
                f"/api/v1/workflows/{workflow_id}/runs/{run_id}/approvals/pending"
            )
            assert pending.status_code == 200
            approval_id = UUID(pending.json()["id"])
            rejected = await client.post(
                f"/api/v1/workflows/{workflow_id}/runs/{run_id}/approvals/{approval_id}/reject",
                json={"note": "No"},
            )
            assert rejected.status_code == 200
            assert rejected.json()["status"] == "rejected"

        run = await postgres_session.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id))
        approval = await postgres_session.scalar(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
        )
        checkpoints = list(
            (
                await postgres_session.scalars(
                    select(WorkflowCheckpoint)
                    .where(WorkflowCheckpoint.run_id == run_id)
                    .order_by(WorkflowCheckpoint.sequence)
                )
            ).all()
        )
        assert approval is not None and approval.status == "rejected"
        assert run is not None and run.status == "cancelled" and run.finished_at is not None
        assert "end" not in run.node_outputs
        assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 2]
        assert checkpoints[-1].pending_node_id == "approval"
        assert checkpoints[-1].interrupt == {
            "type": "approval_required",
            "payload": {"node_id": "approval", "prompt": "Continue?"},
        }
    finally:
        app.dependency_overrides.clear()
