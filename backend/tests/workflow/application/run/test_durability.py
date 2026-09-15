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
        patch("app.services.workflow.application.run.durability.approval_repo") as approval_repo,
    ):
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)
        checkpoint_repo.create_workflow_checkpoint = AsyncMock()
        approval_repo.create_approval_request = AsyncMock()

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
async def test_persist_interruption_updates_paused_run_and_records_interrupt() -> None:
    db = AsyncMock()
    run = make_run()
    run.start()
    run.pause()
    db_run = MagicMock()
    persistence = DurableWorkflowExecutionPersistence(db, db_run)
    with (
        patch("app.services.workflow.application.run.durability.run_repo") as run_repo,
        patch("app.services.workflow.application.run.durability.checkpoint_repo") as checkpoint_repo,
        patch("app.services.workflow.application.run.durability.approval_repo") as approval_repo,
    ):
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)
        checkpoint_repo.create_workflow_checkpoint = AsyncMock()
        approval_repo.create_approval_request = AsyncMock()

        await persistence.persist_node_completion(
            run, completed_node_ids=("start",), pending_node_id="approval"
        )
        await persistence.persist_interruption(
            run,
            completed_node_ids=("start",),
            pending_node_id="approval",
            interrupt={
                "type": "approval_required",
                "payload": {"node_id": "approval", "prompt": "Continue?"},
            },
        )

    checkpoint = checkpoint_repo.create_workflow_checkpoint.await_args.kwargs["checkpoint"]
    assert checkpoint.sequence == 2
    assert checkpoint.completed_node_ids == ("start",)
    assert checkpoint.pending_node_id == "approval"
    assert checkpoint.interrupt == {
        "type": "approval_required",
        "payload": {"node_id": "approval", "prompt": "Continue?"},
    }
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


@pytest.mark.anyio
async def test_interruption_commit_failure_propagates_without_advancing_sequence() -> None:
    db = AsyncMock()
    db.commit.side_effect = RuntimeError("commit failed")
    run = make_run()
    persistence = DurableWorkflowExecutionPersistence(db, MagicMock())
    with (
        patch("app.services.workflow.application.run.durability.run_repo") as run_repo,
        patch("app.services.workflow.application.run.durability.checkpoint_repo") as checkpoint_repo,
        patch("app.services.workflow.application.run.durability.approval_repo") as approval_repo,
    ):
        run_repo.update_workflow_run_state = AsyncMock()
        checkpoint_repo.create_workflow_checkpoint = AsyncMock()
        approval_repo.create_approval_request = AsyncMock()

        with pytest.raises(RuntimeError, match="commit failed"):
            await persistence.persist_interruption(
                run,
                completed_node_ids=("start",),
                pending_node_id="approval",
                interrupt={
                    "type": "approval_required",
                    "payload": {"node_id": "approval", "prompt": "Continue?"},
                },
            )

        db.commit.side_effect = None
        await persistence.persist_interruption(
            run,
            completed_node_ids=("start",),
            pending_node_id="approval",
            interrupt={
                "type": "approval_required",
                "payload": {"node_id": "approval", "prompt": "Continue?"},
            },
        )

    checkpoints = [call.kwargs["checkpoint"] for call in checkpoint_repo.create_workflow_checkpoint.await_args_list]
    assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 1]


@pytest.mark.anyio
async def test_approval_interruption_persists_run_checkpoint_and_request_in_one_commit() -> None:
    db = AsyncMock()
    run = make_run()
    run.start()
    run.pause()
    db_run = MagicMock()
    persistence = DurableWorkflowExecutionPersistence(db, db_run)
    with (
        patch("app.services.workflow.application.run.durability.run_repo") as run_repo,
        patch("app.services.workflow.application.run.durability.checkpoint_repo") as checkpoint_repo,
        patch("app.services.workflow.application.run.durability.approval_repo") as approval_repo,
    ):
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)
        checkpoint_repo.create_workflow_checkpoint = AsyncMock()
        approval_repo.create_approval_request = AsyncMock()

        await persistence.persist_interruption(
            run,
            completed_node_ids=("start",),
            pending_node_id="approval",
            interrupt={
                "type": "approval_required",
                "payload": {"node_id": "approval", "prompt": "Continue?"},
            },
        )

    approval = approval_repo.create_approval_request.await_args.kwargs["approval"]
    assert (approval.status.value, approval.run_id, approval.workflow_revision) == (
        "pending",
        run.id,
        run.workflow_revision,
    )
    assert (approval.node_id, approval.prompt) == ("approval", "Continue?")
    run_repo.update_workflow_run_state.assert_awaited_once()
    checkpoint_repo.create_workflow_checkpoint.assert_awaited_once()
    approval_repo.create_approval_request.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_generic_interruption_creates_no_approval_request() -> None:
    db = AsyncMock()
    persistence = DurableWorkflowExecutionPersistence(db, MagicMock())
    with (
        patch("app.services.workflow.application.run.durability.run_repo") as run_repo,
        patch("app.services.workflow.application.run.durability.checkpoint_repo") as checkpoint_repo,
        patch("app.services.workflow.application.run.durability.approval_repo") as approval_repo,
    ):
        run_repo.update_workflow_run_state = AsyncMock()
        checkpoint_repo.create_workflow_checkpoint = AsyncMock()
        approval_repo.create_approval_request = AsyncMock()
        await persistence.persist_interruption(
            make_run(),
            completed_node_ids=(),
            pending_node_id="wait",
            interrupt={"type": "external_wait", "payload": {}},
        )

    approval_repo.create_approval_request.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "interrupt",
    [
        {"type": "approval_required"},
        {"type": "approval_required", "payload": {"prompt": "Continue?"}},
        {"type": "approval_required", "payload": {"node_id": "approval"}},
        {
            "type": "approval_required",
            "payload": {"node_id": "other", "prompt": "Continue?"},
        },
    ],
)
async def test_malformed_approval_interruption_fails_before_repository_writes(interrupt) -> None:
    db = AsyncMock()
    persistence = DurableWorkflowExecutionPersistence(db, MagicMock())
    with (
        patch("app.services.workflow.application.run.durability.run_repo") as run_repo,
        patch("app.services.workflow.application.run.durability.checkpoint_repo") as checkpoint_repo,
        patch("app.services.workflow.application.run.durability.approval_repo") as approval_repo,
        pytest.raises(ValueError),
    ):
        await persistence.persist_interruption(
            make_run(),
            completed_node_ids=(),
            pending_node_id="approval",
            interrupt=interrupt,
        )

    run_repo.update_workflow_run_state.assert_not_called()
    checkpoint_repo.create_workflow_checkpoint.assert_not_called()
    approval_repo.create_approval_request.assert_not_called()
    db.commit.assert_not_awaited()
