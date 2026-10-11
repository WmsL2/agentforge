"""Fenced write order, sequence, atomic transaction and failure boundaries."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workflow import (
    BackgroundRunStateError,
    FencedDurableWorkflowExecutionPersistence,
    WorkflowCheckpointSequenceError,
    WorkflowExecutionLease,
    WorkflowExecutionLeaseLostError,
    WorkflowRun,
    WorkflowRunError,
    WorkflowRunStatus,
)
from app.services.workflow.application.background import durability


@pytest.fixture
def setup(monkeypatch):
    run = WorkflowRun(uuid4(), uuid4(), 1)
    run.start()
    run.node_outputs = {"start": {}}
    lease = WorkflowExecutionLease(run.id, uuid4(), 1, datetime(2030, 1, 1, tzinfo=UTC))
    db = MagicMock(spec=AsyncSession)
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = db
    events = []
    db.begin.return_value.__aenter__.side_effect = lambda: events.append("begin")

    async def exit_transaction(exc_type, exc, traceback):
        events.append("commit" if exc is None else "rollback")
        return False

    db.begin.return_value.__aexit__.side_effect = exit_transaction
    row = SimpleNamespace(
        id=run.id, workflow_id=run.workflow_id, workflow_revision=1, status="pending"
    )
    mocks = {}
    for module, name, value, event in (
        (durability.claim_repo, "lock_and_validate_execution_lease", True, "fence"),
        (durability.checkpoint_repo, "get_latest_workflow_checkpoint", None, "sequence"),
        (durability.run_repo, "get_workflow_run_by_id", row, "load"),
        (durability.run_repo, "update_workflow_run_state", row, "run"),
        (durability.checkpoint_repo, "create_workflow_checkpoint", None, "checkpoint"),
        (durability.approval_repo, "create_approval_request", None, "approval"),
    ):

        async def action(*args, _event=event, _value=value, **kwargs):
            assert args[0] is db
            events.append(_event)
            return _value

        mock = AsyncMock(side_effect=action)
        mocks[name] = mock
        monkeypatch.setattr(module, name, mock)
    persistence = FencedDurableWorkflowExecutionPersistence(factory, lease)
    return SimpleNamespace(
        run=run,
        lease=lease,
        db=db,
        factory=factory,
        events=events,
        mocks=mocks,
        persistence=persistence,
    )


async def complete(subject):
    await subject.persistence.persist_node_completion(
        subject.run, completed_node_ids=("start",), pending_node_id="end"
    )


@pytest.mark.anyio
async def test_fence_sequence_and_checkpoint_use_same_short_transaction(setup):
    await complete(setup)
    assert setup.events == ["begin", "fence", "sequence", "load", "run", "checkpoint", "commit"]
    checkpoint = setup.mocks["create_workflow_checkpoint"].await_args.kwargs["checkpoint"]
    assert checkpoint.sequence == 1
    assert setup.persistence._next_sequence == 2
    assert setup.persistence.persisted_status is WorkflowRunStatus.RUNNING
    setup.db.commit.assert_not_awaited()
    setup.factory.return_value.__aexit__.assert_awaited_once()


@pytest.mark.anyio
async def test_recovery_appends_sequence_and_uses_fresh_session(setup):
    setup.persistence._next_sequence = 3
    setup.mocks["get_latest_workflow_checkpoint"].side_effect = None
    setup.mocks["get_latest_workflow_checkpoint"].return_value = SimpleNamespace(
        sequence=2, workflow_revision=1
    )
    await complete(setup)
    assert setup.mocks["create_workflow_checkpoint"].await_args.kwargs["checkpoint"].sequence == 3
    setup.mocks["get_latest_workflow_checkpoint"].return_value.sequence = 3
    await complete(setup)
    assert setup.mocks["create_workflow_checkpoint"].await_args.kwargs["checkpoint"].sequence == 4
    assert setup.factory.call_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize("latest", [None, SimpleNamespace(sequence=5, workflow_revision=1)])
async def test_sequence_mismatch_prevents_all_writes(setup, latest):
    setup.persistence._next_sequence = 2
    setup.mocks["get_latest_workflow_checkpoint"].side_effect = None
    setup.mocks["get_latest_workflow_checkpoint"].return_value = latest
    with pytest.raises(WorkflowCheckpointSequenceError):
        await complete(setup)
    setup.mocks["update_workflow_run_state"].assert_not_awaited()
    setup.mocks["create_workflow_checkpoint"].assert_not_awaited()
    assert setup.events[-1] == "rollback" and setup.persistence._next_sequence == 2


@pytest.mark.anyio
async def test_lost_lease_prevents_every_write(setup):
    setup.mocks["lock_and_validate_execution_lease"].side_effect = None
    setup.mocks["lock_and_validate_execution_lease"].return_value = False
    with pytest.raises(WorkflowExecutionLeaseLostError):
        await complete(setup)
    for name in (
        "get_latest_workflow_checkpoint",
        "update_workflow_run_state",
        "create_workflow_checkpoint",
        "create_approval_request",
    ):
        setup.mocks[name].assert_not_awaited()
    assert setup.persistence._next_sequence == 1
    assert setup.persistence.persisted_status is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name", ["update_workflow_run_state", "create_workflow_checkpoint", "create_approval_request"]
)
async def test_write_failure_rolls_back_and_does_not_advance_sequence(setup, name):
    setup.run.pause()
    setup.mocks[name].side_effect = RuntimeError("database failed")
    with pytest.raises(RuntimeError, match="database failed"):
        await setup.persistence.persist_interruption(
            setup.run,
            completed_node_ids=("start",),
            pending_node_id="approval",
            interrupt={
                "type": "approval_required",
                "payload": {"node_id": "approval", "prompt": "Continue?"},
            },
        )
    assert setup.events[-1] == "rollback"
    assert setup.persistence._next_sequence == 1 and setup.persistence.persisted_status is None


@pytest.mark.anyio
@pytest.mark.parametrize("error", [RuntimeError("commit failed"), asyncio.CancelledError()])
async def test_transaction_exit_failure_does_not_advance_local_state(setup, error):
    setup.db.begin.return_value.__aexit__.side_effect = error
    with pytest.raises(type(error)):
        await complete(setup)
    assert setup.persistence._next_sequence == 1
    assert setup.persistence.persisted_status is None


@pytest.mark.anyio
async def test_approval_commits_run_checkpoint_and_request_together(setup):
    setup.run.pause()
    await setup.persistence.persist_interruption(
        setup.run,
        completed_node_ids=("start",),
        pending_node_id="approval",
        interrupt={
            "type": "approval_required",
            "payload": {"node_id": "approval", "prompt": "Continue?"},
        },
    )
    assert setup.events == [
        "begin",
        "fence",
        "sequence",
        "load",
        "run",
        "checkpoint",
        "approval",
        "commit",
    ]
    request = setup.mocks["create_approval_request"].await_args.kwargs["approval"]
    assert request.run_id == setup.run.id and request.node_id == "approval"
    assert setup.persistence.persisted_status is WorkflowRunStatus.PAUSED


@pytest.mark.anyio
async def test_failure_persists_structured_state_without_success_checkpoint(setup):
    setup.run.fail(WorkflowRunError("node_execution_failed", "boom", "b"))
    await setup.persistence.persist_failure(setup.run)
    setup.mocks["update_workflow_run_state"].assert_awaited_once()
    setup.mocks["create_workflow_checkpoint"].assert_not_awaited()
    setup.mocks["create_approval_request"].assert_not_awaited()
    assert setup.persistence.persisted_status is WorkflowRunStatus.FAILED
    assert setup.persistence._next_sequence == 1


@pytest.mark.anyio
async def test_completed_state_has_durable_final_checkpoint(setup):
    setup.run.complete({"end": {}})
    await setup.persistence.persist_node_completion(
        setup.run, completed_node_ids=("start",), pending_node_id=None
    )
    assert setup.persistence.persisted_status is WorkflowRunStatus.COMPLETED


@pytest.mark.anyio
async def test_wrong_run_is_rejected_before_session_creation(setup):
    setup.run.id = uuid4()
    with pytest.raises(BackgroundRunStateError):
        await complete(setup)
    setup.factory.assert_not_called()
