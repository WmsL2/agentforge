"""Trace identity propagation and fine-grained workflow executor events."""

import asyncio
from uuid import uuid4

import pytest

from app.services.agent_runtime import AgentExecutionResult, AgentRuntimeError
from app.services.workflow import (
    AgentNodeExecutor,
    ApprovalNodeExecutor,
    NodeExecutionContext,
    TraceEventKind,
    WorkflowNode,
    WorkflowNodeKind,
)


class Observer:
    def __init__(self, error: Exception | None = None) -> None:
        self.events: list[tuple[object, object, object]] = []
        self.error = error

    async def record_event(self, context, *, kind, payload) -> None:
        self.events.append((context, kind, payload))
        if self.error is not None:
            raise self.error


class Runner:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.request = None

    async def run(self, request):
        self.request = request
        if self.error is not None:
            raise self.error
        return AgentExecutionResult(output={"answer": 42}, metadata={"tokens": 3})


def context(*, step_id=None) -> NodeExecutionContext:
    return NodeExecutionContext(
        run_id=uuid4(), workflow_input={}, upstream_outputs={"start": {}}, node_outputs={}, step_id=step_id
    )


def agent() -> WorkflowNode:
    return WorkflowNode(
        "agent", WorkflowNodeKind.AGENT, {"runner": "langgraph", "instruction": "Analyze."}
    )


def test_agent_events_and_request_share_the_current_run_step_identity() -> None:
    step_id = uuid4()
    execution_context = context(step_id=step_id)
    observer, runner = Observer(), Runner()

    asyncio.run(AgentNodeExecutor({"langgraph": runner}, observer=observer).execute(agent(), execution_context))

    assert runner.request.trace_run_id == execution_context.run_id
    assert runner.request.trace_step_id == step_id
    assert [kind for _, kind, _ in observer.events] == [
        TraceEventKind.AGENT_STARTED,
        TraceEventKind.AGENT_COMPLETED,
    ]
    assert all(event_context.step_id == step_id for event_context, _, _ in observer.events)


def test_agent_failure_records_but_preserves_original_runtime_error() -> None:
    original = AgentRuntimeError("provider_failed", "boom", retryable=True)
    observer = Observer()

    with pytest.raises(AgentRuntimeError) as error_info:
        asyncio.run(
            AgentNodeExecutor({"langgraph": Runner(original)}, observer=observer).execute(
                agent(), context(step_id=uuid4())
            )
        )

    assert error_info.value is original
    assert observer.events[-1][1] is TraceEventKind.AGENT_FAILED
    assert observer.events[-1][2]["error"] == {
        "code": "provider_failed",
        "message": "boom",
        "retryable": True,
    }


def test_agent_trace_is_optional_and_observer_errors_are_fail_open() -> None:
    no_step_observer, runner = Observer(), Runner()
    asyncio.run(AgentNodeExecutor({"langgraph": runner}, observer=no_step_observer).execute(agent(), context()))
    assert no_step_observer.events == []

    failing_observer = Observer(RuntimeError("trace unavailable"))
    result = asyncio.run(
        AgentNodeExecutor({"langgraph": Runner()}, observer=failing_observer).execute(
            agent(), context(step_id=uuid4())
        )
    )
    assert result.output == {"answer": 42}


def test_approval_requested_is_step_bound_and_fail_open() -> None:
    step_id = uuid4()
    execution_context = context(step_id=step_id)
    observer = Observer()
    node = WorkflowNode("approval", WorkflowNodeKind.APPROVAL, {"prompt": "Continue?"})

    result = asyncio.run(ApprovalNodeExecutor(observer=observer).execute(node, execution_context))

    assert result.interrupt is not None
    assert observer.events == [
        (
            observer.events[0][0],
            TraceEventKind.APPROVAL_REQUESTED,
            {"node_id": "approval", "prompt": "Continue?"},
        )
    ]
    assert observer.events[0][0].step_id == step_id
    assert asyncio.run(ApprovalNodeExecutor(observer=Observer(RuntimeError())).execute(node, execution_context)).interrupt
