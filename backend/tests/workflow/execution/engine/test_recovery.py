"""Running recovery validates without mutation and reuses the existing scheduler."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.workflow import (
    DeterministicNodeExecutor,
    WorkflowCheckpoint,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowResumeValidationError,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunTransitionError,
)


def state():
    definition = WorkflowDefinition(
        id=uuid4(),
        name="Recovery",
        entry_node_id="start",
        nodes=(
            WorkflowNode("start", WorkflowNodeKind.START),
            WorkflowNode("a", WorkflowNodeKind.VALUE, config={"value": "A"}),
            WorkflowNode("b", WorkflowNodeKind.VALUE, config={"value": "B"}),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        edges=(
            WorkflowEdge("sa", "start", "a"),
            WorkflowEdge("ab", "a", "b"),
            WorkflowEdge("be", "b", "end"),
        ),
    )
    run = WorkflowRun(uuid4(), definition.id, 1)
    run.start(at=datetime(2026, 1, 1, tzinfo=UTC))
    run.node_outputs = {"untrusted": "ignore"}
    checkpoint = WorkflowCheckpoint(
        uuid4(), run.id, 1, 2, ("start", "a"), {"start": {}, "a": "A"}, pending_node_id="b"
    )
    return definition, run, checkpoint


@pytest.mark.anyio
@pytest.mark.parametrize("pending", ["b", None])
async def test_recovery_skips_committed_nodes_restores_outputs_and_preserves_start(pending):
    definition, run, checkpoint = state()
    checkpoint = replace(checkpoint, pending_node_id=pending)
    started_at = run.started_at
    node_executor = AsyncMock(wraps=DeterministicNodeExecutor())
    persistence = AsyncMock()
    await WorkflowEngine(node_executor).recover_running(
        definition, run, checkpoint, persistence=persistence
    )
    assert run.status is WorkflowRunStatus.COMPLETED
    assert run.started_at == started_at
    assert [call.args[0].id for call in node_executor.execute.await_args_list] == ["b", "end"]
    assert run.node_outputs["a"] == "A" and "untrusted" not in run.node_outputs
    assert persistence.persist_node_completion.await_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status", [status for status in WorkflowRunStatus if status is not WorkflowRunStatus.RUNNING]
)
async def test_recovery_rejects_other_states_without_mutation(status):
    definition, run, checkpoint = state()
    run.status = status
    before = replace(run, node_outputs=dict(run.node_outputs))
    node_executor = AsyncMock()
    with pytest.raises(WorkflowRunTransitionError):
        await WorkflowEngine(node_executor).recover_running(definition, run, checkpoint)
    assert run == before
    node_executor.execute.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changes,code",
    [
        ({"run_id": uuid4()}, "checkpoint_run_mismatch"),
        ({"workflow_revision": 2}, "checkpoint_revision_mismatch"),
        (
            {
                "completed_node_ids": ("ghost",),
                "node_outputs": {"ghost": 1},
                "pending_node_id": None,
            },
            "checkpoint_unknown_completed_node",
        ),
        ({"node_outputs": {"start": {}}}, "checkpoint_output_mismatch"),
        (
            {"completed_node_ids": ("a",), "node_outputs": {"a": "A"}},
            "checkpoint_dependency_incomplete",
        ),
        ({"pending_node_id": "ghost"}, "checkpoint_unknown_pending_node"),
        ({"pending_node_id": "end"}, "checkpoint_pending_not_ready"),
        ({"interrupt": {"type": "approval_required"}}, "running_checkpoint_interrupted"),
        (
            {
                "completed_node_ids": ("start", "a", "b", "end"),
                "node_outputs": {"start": {}, "a": "A", "b": "B", "end": {}},
                "pending_node_id": None,
            },
            "running_checkpoint_already_complete",
        ),
    ],
)
async def test_invalid_checkpoint_does_not_mutate_run_or_execute(changes, code):
    definition, run, checkpoint = state()
    checkpoint = replace(checkpoint, **changes)
    before = replace(run, node_outputs=dict(run.node_outputs))
    node_executor = AsyncMock()
    with pytest.raises(WorkflowResumeValidationError) as error:
        await WorkflowEngine(node_executor).recover_running(definition, run, checkpoint)
    assert error.value.code == code
    assert run == before
    node_executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_running_recovery_does_not_relax_paused_resume():
    definition, run, checkpoint = state()
    node_executor = AsyncMock()
    with pytest.raises(WorkflowRunTransitionError):
        await WorkflowEngine(node_executor).resume(definition, run, checkpoint)
    node_executor.execute.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changes,code",
    [
        ({"id": uuid4()}, "definition_run_mismatch"),
        ({"revision": 2}, "definition_revision_mismatch"),
    ],
)
async def test_recovery_rejects_unrelated_definition_without_mutation(changes, code):
    definition, run, checkpoint = state()
    definition = replace(definition, **changes)
    before = replace(run, node_outputs=dict(run.node_outputs))
    nodes = AsyncMock()
    with pytest.raises(WorkflowResumeValidationError) as error:
        await WorkflowEngine(nodes).recover_running(definition, run, checkpoint)
    assert error.value.code == code
    assert run == before
    nodes.execute.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("error", [RuntimeError("write failed"), asyncio.CancelledError()])
async def test_recovery_persistence_errors_and_cancellation_propagate(error):
    definition, run, checkpoint = state()
    node_executor = AsyncMock(wraps=DeterministicNodeExecutor())
    persistence = AsyncMock()
    persistence.persist_node_completion.side_effect = error
    with pytest.raises(type(error)):
        await WorkflowEngine(node_executor).recover_running(
            definition, run, checkpoint, persistence=persistence
        )
    assert node_executor.execute.await_count == 1
    assert run.status is WorkflowRunStatus.RUNNING
