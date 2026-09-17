"""Tests for the no-op workflow execution observer."""

import asyncio
from uuid import uuid4

from app.services.workflow import (
    NodeExecutionContext,
    NodeExecutionInterrupt,
    NodeExecutionOutcome,
    NodeExecutionResult,
    NoOpWorkflowExecutionObserver,
    RunStepError,
    TraceEventKind,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowObservationContext,
)


def test_noop_start_step_returns_run_context_without_a_step_id() -> None:
    observer = NoOpWorkflowExecutionObserver()
    run_id = uuid4()
    node = WorkflowNode(id="value", kind=WorkflowNodeKind.VALUE)
    execution_context = NodeExecutionContext(run_id=run_id, workflow_input={}, upstream_outputs={}, node_outputs={})

    context = asyncio.run(
        observer.start_step(run_id=run_id, node=node, execution_context=execution_context)
    )

    assert context == WorkflowObservationContext(run_id=run_id, step_id=None)


def test_noop_lifecycle_and_event_methods_have_no_side_effects() -> None:
    observer = NoOpWorkflowExecutionObserver()
    run_id = uuid4()
    context = WorkflowObservationContext(run_id=run_id)
    completed = NodeExecutionResult(output={"answer": "done"}, metadata={"duration_ms": 10})
    interrupted = NodeExecutionResult(
        outcome=NodeExecutionOutcome.INTERRUPTED,
        interrupt=NodeExecutionInterrupt(type="approval_required", payload={"node_id": "approval"}),
    )
    metadata = {"duration_ms": 10}
    payload = {"approval_id": "approval-1"}

    async def observe_without_side_effects() -> None:
        assert await observer.complete_step(context, result=completed) is None
        assert await observer.fail_step(
            context,
            error=RunStepError(code="node_execution_failed", message="boom"),
            metadata=metadata,
        ) is None
        assert await observer.interrupt_step(context, result=interrupted) is None
        assert await observer.record_event(
            context,
            kind=TraceEventKind.APPROVAL_APPROVED,
            payload=payload,
        ) is None

    asyncio.run(observe_without_side_effects())

    assert context == WorkflowObservationContext(run_id=run_id)
    assert completed.metadata == {"duration_ms": 10}
    assert interrupted.interrupt is not None
    assert interrupted.interrupt.payload == {"node_id": "approval"}
    assert metadata == {"duration_ms": 10}
    assert payload == {"approval_id": "approval-1"}
