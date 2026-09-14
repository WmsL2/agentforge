"""AsyncMock unit tests for append-only workflow checkpoint persistence."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories.workflow.checkpoint import repository as checkpoint_repo
from app.services.workflow import WorkflowCheckpoint

CREATED_AT = datetime(2026, 9, 14, 10, tzinfo=UTC)


def make_checkpoint(**kwargs: object) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        id=uuid4(),
        run_id=uuid4(),
        workflow_revision=3,
        sequence=1,
        completed_node_ids=("start",),
        node_outputs={"start": {"request": "hello"}},
        pending_node_id="value",
        interrupt={"kind": "approval"},
        created_at=CREATED_AT,
        **kwargs,
    )  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_create_maps_domain_snapshot_without_committing() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    checkpoint = make_checkpoint()

    created = await checkpoint_repo.create_workflow_checkpoint(db, checkpoint=checkpoint)

    assert (created.id, created.run_id, created.workflow_revision, created.sequence) == (
        checkpoint.id,
        checkpoint.run_id,
        3,
        1,
    )
    assert created.completed_node_ids == ["start"]
    assert created.node_outputs == {"start": {"request": "hello"}}
    assert created.pending_node_id == "value"
    assert created.interrupt == {"kind": "approval"}
    assert created.created_at == CREATED_AT
    db.add.assert_called_once_with(created)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_get_latest_scopes_orders_and_returns_newest_row() -> None:
    db = AsyncMock()
    run_id = uuid4()
    stored = SimpleNamespace(id=uuid4(), sequence=2)
    result = MagicMock()
    result.scalar_one_or_none.return_value = stored
    db.execute.return_value = result

    latest = await checkpoint_repo.get_latest_workflow_checkpoint(db, run_id)

    assert latest is stored
    statement = db.execute.await_args.args[0]
    assert "workflow_checkpoints.run_id" in str(statement)
    assert "ORDER BY workflow_checkpoints.sequence DESC" in str(statement)
    assert "LIMIT" in str(statement)


@pytest.mark.anyio
async def test_get_latest_returns_none_when_checkpoint_does_not_exist() -> None:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    assert await checkpoint_repo.get_latest_workflow_checkpoint(db, uuid4()) is None
