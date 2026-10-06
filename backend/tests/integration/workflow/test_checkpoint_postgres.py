"""Opt-in real PostgreSQL round-trip coverage for workflow checkpoints."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun
from app.db.models.workflow import WorkflowCheckpoint as DBWorkflowCheckpoint
from app.repositories import workspace as workspace_repo
from app.repositories.workflow.checkpoint import (
    create_workflow_checkpoint,
    get_latest_workflow_checkpoint,
)
from app.services.workflow import WorkflowCheckpoint
from app.services.workspace.domain import WorkspaceRole


@pytest.mark.anyio
async def test_checkpoint_round_trip_uses_real_postgresql(postgres_session: AsyncSession) -> None:
    user_id = uuid4()
    workflow_id = uuid4()
    run_id = uuid4()
    user = User(id=user_id, email=f"checkpoint-{user_id.hex}@example.invalid")
    postgres_session.add(user)
    await postgres_session.flush()
    workspace = await workspace_repo.create_workspace(
        postgres_session,
        name="Checkpoint persistence",
        created_by_user_id=user.id,
    )
    await workspace_repo.create_membership(
        postgres_session,
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    postgres_session.add_all(
        [
            Workflow(
                id=workflow_id,
                user_id=user.id,
                workspace_id=workspace.id,
                name="Checkpoint persistence",
                definition={"nodes": [], "edges": []},
                revision=4,
            ),
            WorkflowRun(
                id=run_id,
                workflow_id=workflow_id,
                workflow_revision=4,
                definition_snapshot={"nodes": [], "edges": []},
                status="paused",
                input={},
                node_outputs={},
                output=None,
                error=None,
                started_at=None,
                finished_at=None,
            ),
        ]
    )
    await postgres_session.flush()
    postgres_session.info["e2e_workflow_id"] = workflow_id
    postgres_session.info["e2e_run_id"] = run_id

    first = await create_workflow_checkpoint(
        postgres_session,
        checkpoint=WorkflowCheckpoint(
            id=uuid4(),
            run_id=run_id,
            workflow_revision=4,
            sequence=1,
            completed_node_ids=("start",),
            node_outputs={"start": {"request": "hello"}},
            pending_node_id="value",
            interrupt=None,
        ),
    )
    second = await create_workflow_checkpoint(
        postgres_session,
        checkpoint=WorkflowCheckpoint(
            id=uuid4(),
            run_id=run_id,
            workflow_revision=4,
            sequence=2,
            completed_node_ids=("start", "value"),
            node_outputs={"start": {"request": "hello"}, "value": 42},
            pending_node_id="end",
            interrupt={"kind": "approval"},
        ),
    )

    assert (
        await postgres_session.scalar(
            select(func.count())
            .select_from(DBWorkflowCheckpoint)
            .where(DBWorkflowCheckpoint.run_id == run_id)
        )
        == 2
    )
    latest = await get_latest_workflow_checkpoint(postgres_session, run_id)

    assert first.sequence == 1
    assert latest is second
    assert latest is not None
    assert latest.sequence == 2
    assert latest.workflow_revision == 4
    assert latest.completed_node_ids == ["start", "value"]
    assert latest.node_outputs == {"start": {"request": "hello"}, "value": 42}
    assert latest.pending_node_id == "end"
    assert latest.interrupt == {"kind": "approval"}
