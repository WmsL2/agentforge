"""Tests for deterministic workflow execution orchestration."""

import asyncio
from collections.abc import Mapping
from uuid import uuid4

import pytest

from app.services.workflow import (
    DeterministicNodeExecutor,
    NodeExecutionContext,
    NodeExecutionResult,
    WorkflowCheckpoint,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowExecutionValidationError,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowResumeValidationError,
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


class RecordingPersistence:
    def __init__(self, fail_on_call: int | None = None):
        self.calls: list[dict[str, object]] = []
        self._fail_on_call = fail_on_call

    async def persist_node_completion(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str | None,
    ) -> None:
        self.calls.append(
            {
                "status": run.status,
                "output": None if run.output is None else dict(run.output),
                "completed_node_ids": completed_node_ids,
                "pending_node_id": pending_node_id,
            }
        )
        if self._fail_on_call == len(self.calls):
            raise RuntimeError("durability failed")


def execute(workflow: WorkflowDefinition, workflow_run: WorkflowRun, executor: RecordingExecutor):
    return asyncio.run(WorkflowEngine(executor).execute(workflow, workflow_run))


def resume(
    workflow: WorkflowDefinition,
    workflow_run: WorkflowRun,
    checkpoint: WorkflowCheckpoint,
    executor: RecordingExecutor,
):
    return asyncio.run(WorkflowEngine(executor).resume(workflow, workflow_run, checkpoint))


def paused_run(**kwargs: object) -> WorkflowRun:
    workflow_run = run(**kwargs)
    workflow_run.start()
    workflow_run.pause()
    return workflow_run


def checkpoint(
    workflow_run: WorkflowRun,
    *,
    completed_node_ids: tuple[str, ...],
    node_outputs: dict[str, object],
    pending_node_id: str | None = None,
    **kwargs: object,
) -> WorkflowCheckpoint:
    values: dict[str, object] = {
        "id": uuid4(),
        "run_id": workflow_run.id,
        "workflow_revision": workflow_run.workflow_revision,
        "sequence": 1,
        "completed_node_ids": completed_node_ids,
        "node_outputs": node_outputs,
        "pending_node_id": pending_node_id,
    }
    values.update(kwargs)
    return WorkflowCheckpoint(**values)  # type: ignore[arg-type]


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
        WorkflowRunStatus.PAUSED,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.CANCELLED,
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


def test_resume_skips_completed_nodes_and_restores_checkpoint_outputs() -> None:
    executor = RecordingExecutor()
    workflow_run = paused_run(input={"question": "hello"}, node_outputs={"stale": "value"})
    saved = checkpoint(
        workflow_run,
        completed_node_ids=("start", "value"),
        node_outputs={"start": {"question": "hello"}, "value": 100},
        pending_node_id="end",
    )

    returned = resume(linear_definition(), workflow_run, saved, executor)

    assert returned is workflow_run
    assert workflow_run.status is WorkflowRunStatus.COMPLETED
    assert executor.calls == ["end"]
    assert executor.contexts["end"].upstream_outputs == {"value": 100}
    assert workflow_run.node_outputs == {
        "start": {"question": "hello"},
        "value": 100,
        "end": {"value": 100},
    }


def test_resume_without_pending_node_uses_first_ready_incomplete_node() -> None:
    executor = RecordingExecutor()
    workflow_run = paused_run()
    saved = checkpoint(
        workflow_run,
        completed_node_ids=("start",),
        node_outputs={"start": {}},
    )

    resume(linear_definition(), workflow_run, saved, executor)

    assert executor.calls == ["value", "end"]


def test_resume_honors_pending_node_before_declaration_order() -> None:
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
    workflow_run = paused_run()
    saved = checkpoint(
        workflow_run,
        completed_node_ids=("start",),
        node_outputs={"start": {}},
        pending_node_id="b",
    )

    resume(workflow, workflow_run, saved, executor)

    assert executor.calls == ["b", "a", "end"]


def test_resume_failure_marks_run_failed_and_retains_restored_outputs() -> None:
    executor = FailingExecutor("value")
    workflow_run = paused_run()
    saved = checkpoint(
        workflow_run,
        completed_node_ids=("start",),
        node_outputs={"start": {}},
        pending_node_id="value",
    )

    resume(linear_definition(), workflow_run, saved, executor)

    assert workflow_run.status is WorkflowRunStatus.FAILED
    assert workflow_run.error is not None
    assert workflow_run.error.code == "node_execution_failed"
    assert workflow_run.node_outputs == {"start": {}}


def test_resume_all_completed_checkpoint_completes_without_executor_calls() -> None:
    executor = RecordingExecutor()
    workflow_run = paused_run()
    saved = checkpoint(
        workflow_run,
        completed_node_ids=("start", "value", "end"),
        node_outputs={"start": {}, "value": 100, "end": {"value": 100}},
    )

    resume(linear_definition(), workflow_run, saved, executor)

    assert executor.calls == []
    assert workflow_run.status is WorkflowRunStatus.COMPLETED
    assert workflow_run.output == {"end": {"value": 100}}


@pytest.mark.parametrize(
    "status",
    [
        WorkflowRunStatus.PENDING,
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.CANCELLED,
    ],
)
def test_resume_rejects_non_paused_runs_without_calling_executor(status: WorkflowRunStatus) -> None:
    executor = RecordingExecutor()
    workflow_run = run(status=status)
    saved = checkpoint(
        workflow_run,
        completed_node_ids=("start",),
        node_outputs={"start": {}},
        pending_node_id="value",
    )

    with pytest.raises(WorkflowRunTransitionError):
        resume(linear_definition(), workflow_run, saved, executor)

    assert workflow_run.status is status
    assert executor.calls == []


@pytest.mark.parametrize(
    ("code", "checkpoint_kwargs"),
    [
        ("checkpoint_run_mismatch", {"run_id": uuid4()}),
        ("checkpoint_revision_mismatch", {"workflow_revision": 2}),
        (
            "checkpoint_unknown_completed_node",
            {"completed_node_ids": ("unknown",), "node_outputs": {"unknown": None}},
        ),
        ("checkpoint_output_mismatch", {"node_outputs": {}}),
        (
            "checkpoint_dependency_incomplete",
            {"completed_node_ids": ("value",), "node_outputs": {"value": 100}},
        ),
        ("checkpoint_unknown_pending_node", {"pending_node_id": "unknown"}),
        ("checkpoint_pending_not_ready", {"pending_node_id": "end"}),
    ],
)
def test_resume_rejects_invalid_checkpoint_without_mutating_run(
    code: str, checkpoint_kwargs: dict[str, object]
) -> None:
    executor = RecordingExecutor()
    workflow_run = paused_run(node_outputs={"stale": "value"})
    original_started_at = workflow_run.started_at
    checkpoint_values: dict[str, object] = {
        "completed_node_ids": ("start",),
        "node_outputs": {"start": {}},
    }
    checkpoint_values.update(checkpoint_kwargs)
    saved = checkpoint(workflow_run, **checkpoint_values)  # type: ignore[arg-type]

    with pytest.raises(WorkflowResumeValidationError) as exc_info:
        resume(linear_definition(), workflow_run, saved, executor)

    assert exc_info.value.code == code
    assert workflow_run.status is WorkflowRunStatus.PAUSED
    assert workflow_run.started_at == original_started_at
    assert workflow_run.finished_at is None
    assert workflow_run.node_outputs == {"stale": "value"}
    assert executor.calls == []


def test_resume_invalid_definition_does_not_mutate_paused_run() -> None:
    invalid = definition(
        (
            node("start", WorkflowNodeKind.START),
            node("end", WorkflowNodeKind.END),
        ),
        (edge("cycle", "end", "start"),),
    )
    executor = RecordingExecutor()
    workflow_run = paused_run(node_outputs={"stale": "value"})
    saved = checkpoint(
        workflow_run,
        completed_node_ids=("start",),
        node_outputs={"start": {}},
    )

    with pytest.raises(WorkflowExecutionValidationError):
        resume(invalid, workflow_run, saved, executor)

    assert workflow_run.status is WorkflowRunStatus.PAUSED
    assert workflow_run.node_outputs == {"stale": "value"}
    assert executor.calls == []


def test_execute_persists_every_successful_node_in_declaration_order() -> None:
    executor = RecordingExecutor()
    persistence = RecordingPersistence()

    execute_result = asyncio.run(
        WorkflowEngine(executor).execute(linear_definition(), run(), persistence=persistence)
    )

    assert execute_result.status is WorkflowRunStatus.COMPLETED
    assert [call["completed_node_ids"] for call in persistence.calls] == [
        ("start",),
        ("start", "value"),
        ("start", "value", "end"),
    ]
    assert [call["pending_node_id"] for call in persistence.calls] == ["value", "end", None]
    assert persistence.calls[-1]["status"] is WorkflowRunStatus.COMPLETED
    assert persistence.calls[-1]["output"] == {"end": {"value": 100}}


def test_persistence_failure_stops_before_next_node_and_is_not_node_failure() -> None:
    executor = RecordingExecutor()
    persistence = RecordingPersistence(fail_on_call=2)
    workflow_run = run()

    with pytest.raises(RuntimeError, match="durability failed"):
        asyncio.run(
            WorkflowEngine(executor).execute(
                linear_definition(), workflow_run, persistence=persistence
            )
        )

    assert executor.calls == ["start", "value"]
    assert workflow_run.status is WorkflowRunStatus.RUNNING
    assert workflow_run.error is None


def test_resume_persists_each_newly_completed_node() -> None:
    executor = RecordingExecutor()
    persistence = RecordingPersistence()
    workflow_run = paused_run()
    saved = checkpoint(
        workflow_run,
        completed_node_ids=("start",),
        node_outputs={"start": {}},
        pending_node_id="value",
    )

    asyncio.run(WorkflowEngine(executor).resume(linear_definition(), workflow_run, saved, persistence=persistence))

    assert executor.calls == ["value", "end"]
    assert [call["completed_node_ids"] for call in persistence.calls] == [
        ("start", "value"),
        ("start", "value", "end"),
    ]
