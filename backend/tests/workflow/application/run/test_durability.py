"""Tests for application-owned durable workflow execution persistence."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.workflow import WorkflowRun
from app.services.workflow.application.run.durability import DurableWorkflowExecutionPersistence


def make_run() -> WorkflowRun:
    return WorkflowRun(id=uuid4(), workflow_id=uuid4(), workflow_revision=4)


@pytest.mark.anyio
async def test_persist_node_completion_creates_sequence_one_and_commits_once() -> None:
    db = AsyncMock()
    run = make_run()
    db_run = MagicMock()
    persistence = DurableWorkflowExecutionPersistence(db, db_run)
    with (
        patch("app.services.workflow.application.run.durability.run_repo") as run_repo,
        patch("app.services.workflow.application.run.durability.checkpoint_repo") as checkpoint_repo,
    ):
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)
        checkpoint_repo.create_workflow_checkpoint = AsyncMock()

        await persistence.persist_node_completion(
            run,
            completed_node_ids=("start",),
            pending_node_id="value",
        )

    run_repo.update_workflow_run_state.assert_awaited_once_with(db, db_run=db_run, run=run)
    checkpoint = checkpoint_repo.create_workflow_checkpoint.await_args.kwargs["checkpoint"]
    assert checkpoint.run_id == run.id
    assert checkpoint.workflow_revision == 4
    assert checkpoint.sequence == 1
    assert checkpoint.completed_node_ids == ("start",)
    assert checkpoint.node_outputs == {}
    assert checkpoint.pending_node_id == "value"
    assert checkpoint.interrupt is None
    db.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_sequence_increments_only_after_successful_commit() -> None:
    db = AsyncMock()
    run = make_run()
    persistence = DurableWorkflowExecutionPersistence(db, MagicMock())
    with (
        patch("app.services.workflow.application.run.durability.run_repo") as run_repo,
        patch("app.services.workflow.application.run.durability.checkpoint_repo") as checkpoint_repo,
    ):
        run_repo.update_workflow_run_state = AsyncMock()
        checkpoint_repo.create_workflow_checkpoint = AsyncMock()

        await persistence.persist_node_completion(
            run,
            completed_node_ids=("start",),
            pending_node_id="value",
        )
        await persistence.persist_node_completion(
            run,
            completed_node_ids=("start", "value"),
            pending_node_id="end",
        )

    checkpoints = [call.kwargs["checkpoint"] for call in checkpoint_repo.create_workflow_checkpoint.await_args_list]
    assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 2]
    assert db.commit.await_count == 2


@pytest.mark.anyio
async def test_commit_failure_propagates_without_advancing_sequence() -> None:
    db = AsyncMock()
    db.commit.side_effect = RuntimeError("commit failed")
    run = make_run()
    persistence = DurableWorkflowExecutionPersistence(db, MagicMock())
    with (
        patch("app.services.workflow.application.run.durability.run_repo") as run_repo,
        patch("app.services.workflow.application.run.durability.checkpoint_repo") as checkpoint_repo,
    ):
        run_repo.update_workflow_run_state = AsyncMock()
        checkpoint_repo.create_workflow_checkpoint = AsyncMock()

        with pytest.raises(RuntimeError, match="commit failed"):
            await persistence.persist_node_completion(
                run,
                completed_node_ids=("start",),
                pending_node_id="value",
            )

        db.commit.side_effect = None
        await persistence.persist_node_completion(
            run,
            completed_node_ids=("start",),
            pending_node_id="value",
        )

    checkpoints = [call.kwargs["checkpoint"] for call in checkpoint_repo.create_workflow_checkpoint.await_args_list]
    assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 1]
