"""AsyncMock unit tests for workflow-run persistence primitives."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.execution.run import WorkflowRun, WorkflowRunError

STARTED_AT = datetime(2026, 9, 1, 10, tzinfo=UTC)
FINISHED_AT = datetime(2026, 9, 1, 10, 5, tzinfo=UTC)


def make_run(**kwargs: object) -> WorkflowRun:
    return WorkflowRun(id=uuid4(), workflow_id=uuid4(), workflow_revision=4, **kwargs)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_create_persists_exact_identity_snapshot_and_state() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    run = make_run(input={"request": "hello"})
    snapshot = {
        "schema_version": 1,
        "entry_node_id": "start",
        "nodes": [],
        "edges": [],
        "metadata": {},
    }

    created = await run_repo.create_workflow_run(db, run=run, definition_snapshot=snapshot)

    assert (created.id, created.workflow_id, created.workflow_revision) == (
        run.id,
        run.workflow_id,
        4,
    )
    assert created.definition_snapshot == snapshot
    assert created.status == "pending"
    assert created.input == {"request": "hello"}
    assert created.node_outputs == {}
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_get_list_and_count_are_scoped_to_workflow() -> None:
    db = AsyncMock()
    workflow_id = uuid4()
    stored = SimpleNamespace(id=uuid4())
    result = MagicMock()
    result.scalars.return_value.all.return_value = [stored]
    db.get.return_value = stored
    db.execute.return_value = result
    db.scalar.return_value = 1

    assert await run_repo.get_workflow_run_by_id(db, stored.id) is stored
    assert await run_repo.list_workflow_runs_by_workflow(db, workflow_id, skip=2, limit=3) == [
        stored
    ]
    assert await run_repo.count_workflow_runs_by_workflow(db, workflow_id) == 1
    db.get.assert_awaited_once_with(run_repo.DBWorkflowRun, stored.id)
    db.execute.assert_awaited_once()
    db.scalar.assert_awaited_once()


@pytest.mark.anyio
async def test_update_persists_only_mutable_lifecycle_state() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    immutable_workflow_id = uuid4()
    snapshot = {"schema_version": 1}
    stored = SimpleNamespace(
        id=uuid4(),
        workflow_id=immutable_workflow_id,
        workflow_revision=9,
        definition_snapshot=snapshot,
        input={"fixed": True},
        status="pending",
        node_outputs={},
        output=None,
        error=None,
        started_at=None,
        finished_at=None,
    )
    run = WorkflowRun(
        id=stored.id,
        workflow_id=uuid4(),
        workflow_revision=1,
        input={"different": True},
    )
    run.start(at=STARTED_AT)
    run.node_outputs["value"] = 10
    run.complete({"end": {"value": 10}}, at=FINISHED_AT)

    updated = await run_repo.update_workflow_run_state(db, db_run=stored, run=run)

    assert updated is stored
    assert stored.workflow_id == immutable_workflow_id
    assert stored.workflow_revision == 9
    assert stored.definition_snapshot is snapshot
    assert stored.input == {"fixed": True}
    assert stored.status == "completed"
    assert stored.node_outputs == {"value": 10}
    assert stored.output == {"end": {"value": 10}}
    assert stored.error is None
    assert (stored.started_at, stored.finished_at) == (STARTED_AT, FINISHED_AT)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(stored)
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_update_persists_failed_structured_error() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    stored = SimpleNamespace(
        id=uuid4(),
        workflow_id=uuid4(),
        workflow_revision=1,
        definition_snapshot={},
        input={},
    )
    run = WorkflowRun(id=stored.id, workflow_id=stored.workflow_id, workflow_revision=1)
    run.start(at=STARTED_AT)
    run.fail(
        WorkflowRunError(code="node_execution_failed", message="boom", node_id="value"),
        at=FINISHED_AT,
    )

    await run_repo.update_workflow_run_state(db, db_run=stored, run=run)

    assert stored.status == "failed"
    assert stored.output is None
    assert stored.error == {
        "code": "node_execution_failed",
        "message": "boom",
        "node_id": "value",
    }
