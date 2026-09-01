"""Tests for deterministic workflow execution orchestration."""

import asyncio
from collections.abc import Mapping
from uuid import uuid4

import pytest

from app.services.workflow import (
    DeterministicNodeExecutor,
    NodeExecutionContext,
    NodeExecutionResult,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowExecutionValidationError,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunTransitionError,
)


def node(node_id: str, kind: WorkflowNodeKind, **kwargs: object) -> WorkflowNode:
    return WorkflowNode(id=node_id, kind=kind, **kwargs)  # type: ignore[arg-type]


def edge(edge_id: str, source: str, target: str) -> WorkflowEdge:
    return WorkflowEdge(id=edge_id, source=source, target=target)


def definition(
    nodes: tuple[WorkflowNode, ...], edges: tuple[WorkflowEdge, ...]
) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=uuid4(), name="Execution test", entry_node_id="start", nodes=nodes, edges=edges
    )


def run(**kwargs: object) -> WorkflowRun:
    return WorkflowRun(id=uuid4(), workflow_id=uuid4(), workflow_revision=1, **kwargs)  # type: ignore[arg-type]


def linear_definition() -> WorkflowDefinition:
    return definition(
        (
            node("start", WorkflowNodeKind.START),
            node("value", WorkflowNodeKind.VALUE, config={"value": 100}),
            node("end", WorkflowNodeKind.END),
        ),
        (edge("start-value", "start", "value"), edge("value-end", "value", "end")),
    )


class RecordingExecutor:
    def __init__(self, delegate: DeterministicNodeExecutor | None = None):
        self.calls: list[str] = []
        self.contexts: dict[str, NodeExecutionContext] = {}
        self._delegate = delegate or DeterministicNodeExecutor()

    async def execute(
        self, workflow_node: WorkflowNode, context: NodeExecutionContext
    ) -> NodeExecutionResult:
        self.calls.append(workflow_node.id)
        self.contexts[workflow_node.id] = context
        return await self._delegate.execute(workflow_node, context)


class FailingExecutor(RecordingExecutor):
    def __init__(self, failing_node_id: str):
        super().__init__()
        self._failing_node_id = failing_node_id

    async def execute(
        self, workflow_node: WorkflowNode, context: NodeExecutionContext
    ) -> NodeExecutionResult:
        self.calls.append(workflow_node.id)
        self.contexts[workflow_node.id] = context
        if workflow_node.id == self._failing_node_id:
            raise RuntimeError("boom")
        return await self._delegate.execute(workflow_node, context)


def execute(workflow: WorkflowDefinition, workflow_run: WorkflowRun, executor: RecordingExecutor):
    return asyncio.run(WorkflowEngine(executor).execute(workflow, workflow_run))


def test_linear_execution_completes_the_same_run_with_end_keyed_output() -> None:
    executor = RecordingExecutor()
    workflow_run = run(input={"customer_id": 123})

    returned = execute(linear_definition(), workflow_run, executor)

    assert returned is workflow_run
    assert workflow_run.status is WorkflowRunStatus.COMPLETED
    assert workflow_run.started_at is not None
    assert workflow_run.finished_at is not None
    assert workflow_run.error is None
    assert executor.calls == ["start", "value", "end"]
    assert workflow_run.node_outputs == {
        "start": {"customer_id": 123},
        "value": 100,
        "end": {"value": 100},
    }
    assert workflow_run.output == {"end": {"value": 100}}


def test_fan_out_ready_nodes_execute_in_declaration_order() -> None:
    workflow = definition(
        (
            node("start", WorkflowNodeKind.START),
            node("a", WorkflowNodeKind.VALUE, config={"value": "A"}),
            node("b", WorkflowNodeKind.VALUE, config={"value": "B"}),
            node("end", WorkflowNodeKind.END),
        ),
        (
            edge("start-a", "start", "a"),
            edge("start-b", "start", "b"),
            edge("a-end", "a", "end"),
            edge("b-end", "b", "end"),
        ),
    )
    executor = RecordingExecutor()

    execute(workflow, run(), executor)

    assert executor.calls == ["start", "a", "b", "end"]


def test_fan_in_waits_for_all_direct_predecessors_and_passes_only_them() -> None:
    workflow = definition(
        (
            node("start", WorkflowNodeKind.START),
            node("a", WorkflowNodeKind.VALUE, config={"value": "A"}),
            node("b", WorkflowNodeKind.VALUE, config={"value": "B"}),
            node("end", WorkflowNodeKind.END),
        ),
        (
            edge("start-a", "start", "a"),
            edge("start-b", "start", "b"),
            edge("a-end", "a", "end"),
            edge("b-end", "b", "end"),
        ),
    )
    executor = RecordingExecutor()

    execute(workflow, run(), executor)

    assert executor.calls.index("end") > executor.calls.index("a")
    assert executor.calls.index("end") > executor.calls.index("b")
    assert executor.contexts["end"].upstream_outputs == {"a": "A", "b": "B"}
    assert executor.contexts["end"].node_outputs == {
        "start": {},
        "a": "A",
        "b": "B",
    }


def test_multiple_end_nodes_are_aggregated_in_declaration_order() -> None:
    workflow = definition(
        (
            node("start", WorkflowNodeKind.START),
            node("value", WorkflowNodeKind.VALUE, config={"value": 7}),
            node("success_end", WorkflowNodeKind.END),
            node("audit_end", WorkflowNodeKind.END),
        ),
        (
            edge("start-value", "start", "value"),
            edge("value-success", "value", "success_end"),
            edge("value-audit", "value", "audit_end"),
        ),
    )
    executor = RecordingExecutor()
    workflow_run = run()

    execute(workflow, workflow_run, executor)

    assert executor.calls == ["start", "value", "success_end", "audit_end"]
    assert list(workflow_run.output or {}) == ["success_end", "audit_end"]
    assert workflow_run.output == {
        "success_end": {"value": 7},
        "audit_end": {"value": 7},
    }


def test_invalid_definition_does_not_start_run_or_call_executor() -> None:
    invalid = definition(
        (
            node("start", WorkflowNodeKind.START),
            node("value", WorkflowNodeKind.VALUE),
            node("end", WorkflowNodeKind.END),
        ),
        (
            edge("start-value", "start", "value"),
            edge("cycle", "value", "value"),
            edge("value-end", "value", "end"),
        ),
    )
    executor = RecordingExecutor()
    workflow_run = run()

    with pytest.raises(WorkflowExecutionValidationError) as exc_info:
        execute(invalid, workflow_run, executor)

    assert exc_info.value.validation_result.issues
    assert workflow_run.status is WorkflowRunStatus.PENDING
    assert executor.calls == []


def test_executor_failure_fails_run_and_stops_scheduling() -> None:
    workflow = definition(
        (
            node("start", WorkflowNodeKind.START),
            node("a", WorkflowNodeKind.VALUE, config={"value": "A"}),
            node("b", WorkflowNodeKind.VALUE, config={"value": "B"}),
            node("end", WorkflowNodeKind.END),
        ),
        (
            edge("start-a", "start", "a"),
            edge("start-b", "start", "b"),
            edge("a-end", "a", "end"),
            edge("b-end", "b", "end"),
        ),
    )
    executor = FailingExecutor("b")
    workflow_run = run()

    execute(workflow, workflow_run, executor)

    assert workflow_run.status is WorkflowRunStatus.FAILED
    assert workflow_run.error is not None
    assert workflow_run.error.code == "node_execution_failed"
    assert workflow_run.error.message == "boom"
    assert workflow_run.error.node_id == "b"
    assert workflow_run.node_outputs == {"start": {}, "a": "A"}
    assert "b" not in workflow_run.node_outputs
    assert "end" not in executor.calls
    assert workflow_run.output is None
    assert workflow_run.finished_at is not None


@pytest.mark.parametrize(
    "status",
    [
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
    ],
)
def test_existing_run_lifecycle_protects_against_restart(status: WorkflowRunStatus) -> None:
    executor = RecordingExecutor()

    with pytest.raises(WorkflowRunTransitionError):
        execute(linear_definition(), run(status=status), executor)

    assert executor.calls == []


def test_executor_receives_read_only_snapshots_not_workflow_run() -> None:
    executor = RecordingExecutor()
    workflow_run = run(input={"request": "immutable at the boundary"})

    execute(linear_definition(), workflow_run, executor)

    start_context = executor.contexts["start"]
    assert not isinstance(start_context, WorkflowRun)
    assert isinstance(start_context.workflow_input, Mapping)
    with pytest.raises(TypeError):
        start_context.node_outputs["injected"] = "no"  # type: ignore[index]
