"""WorkflowEngine observer lifecycle and fail-open integration tests."""

import asyncio
from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest

from app.services.workflow import (
    NodeExecutionContext,
    NodeExecutionInterrupt,
    NodeExecutionOutcome,
    NodeExecutionResult,
    RunStepError,
    WorkflowCheckpoint,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowExecutionValidationError,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowObservationContext,
    WorkflowRun,
    WorkflowRunStatus,
)


def workflow(nodes: tuple[WorkflowNode, ...], edges: tuple[WorkflowEdge, ...]) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=uuid4(), name="Observer test", entry_node_id="start", nodes=nodes, edges=edges
    )


def linear_workflow() -> WorkflowDefinition:
    return workflow(
        (
            WorkflowNode("start", WorkflowNodeKind.START),
            WorkflowNode("value", WorkflowNodeKind.VALUE, {"value": 100}),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        (WorkflowEdge("start-value", "start", "value"), WorkflowEdge("value-end", "value", "end")),
    )


def approval_workflow() -> WorkflowDefinition:
    return workflow(
        (
            WorkflowNode("start", WorkflowNodeKind.START),
            WorkflowNode("approval", WorkflowNodeKind.APPROVAL, {"prompt": "Continue?"}),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        (
            WorkflowEdge("start-approval", "start", "approval"),
            WorkflowEdge("approval-end", "approval", "end"),
        ),
    )


def run() -> WorkflowRun:
    return WorkflowRun(id=uuid4(), workflow_id=uuid4(), workflow_revision=1)


class ScriptedExecutor:
    def __init__(self, timeline: list[str], *, fail_node: str | None = None):
        self.timeline = timeline
        self.fail_node = fail_node
        self.calls: list[str] = []

    async def execute(
        self, node: WorkflowNode, context: NodeExecutionContext
    ) -> NodeExecutionResult:
        self.timeline.append(f"execute:{node.id}")
        self.calls.append(node.id)
        if node.id == self.fail_node:
            raise RuntimeError("executor exploded")
        if node.kind is WorkflowNodeKind.APPROVAL:
            return NodeExecutionResult(
                outcome=NodeExecutionOutcome.INTERRUPTED,
                interrupt=NodeExecutionInterrupt(
                    type="approval_required", payload={"node_id": node.id}
                ),
            )
        if node.kind is WorkflowNodeKind.START:
            return NodeExecutionResult(output={})
        if node.kind is WorkflowNodeKind.VALUE:
            return NodeExecutionResult(output=node.config["value"])
        return NodeExecutionResult(output={"value": 100})


class RecordingObserver:
    def __init__(self, timeline: list[str], *, raise_on: str | None = None):
        self.timeline = timeline
        self.raise_on = raise_on
        self.contexts: dict[str, WorkflowObservationContext] = {}
        self.completed: list[tuple[WorkflowObservationContext, NodeExecutionResult]] = []
        self.failed: list[tuple[WorkflowObservationContext, RunStepError, Mapping[str, object]]] = []
        self.interrupted: list[tuple[WorkflowObservationContext, NodeExecutionResult]] = []

    async def start_step(
        self,
        *,
        run_id: UUID,
        node: WorkflowNode,
        execution_context: NodeExecutionContext,
    ) -> WorkflowObservationContext:
        self.timeline.append(f"start:{node.id}")
        if self.raise_on == "start":
            raise RuntimeError("observer start failed")
        context = WorkflowObservationContext(run_id=run_id, step_id=uuid4())
        self.contexts[node.id] = context
        return context

    async def complete_step(
        self, context: WorkflowObservationContext, *, result: NodeExecutionResult
    ) -> None:
        self.timeline.append("complete")
        self.completed.append((context, result))
        if self.raise_on == "complete":
            raise RuntimeError("observer complete failed")

    async def fail_step(
        self,
        context: WorkflowObservationContext,
        *,
        error: RunStepError,
        metadata: Mapping[str, object],
    ) -> None:
        self.timeline.append("fail")
        self.failed.append((context, error, metadata))
        if self.raise_on == "fail":
            raise RuntimeError("observer fail failed")

    async def interrupt_step(
        self, context: WorkflowObservationContext, *, result: NodeExecutionResult
    ) -> None:
        self.timeline.append("interrupt")
        self.interrupted.append((context, result))
        if self.raise_on == "interrupt":
            raise RuntimeError("observer interrupt failed")

    async def record_event(
        self, context: WorkflowObservationContext, *, kind: object, payload: Mapping[str, object]
    ) -> None:
        raise AssertionError("WorkflowEngine must not call record_event")


class TimelinePersistence:
    def __init__(self, timeline: list[str]):
        self.timeline = timeline

    async def persist_node_completion(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str | None,
    ) -> None:
        self.timeline.append("persist_complete")

    async def persist_interruption(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str,
        interrupt: Mapping[str, object],
    ) -> None:
        self.timeline.append("persist_interrupt")


def execute(engine: WorkflowEngine, definition: WorkflowDefinition, workflow_run: WorkflowRun, **kwargs: object) -> WorkflowRun:
    return asyncio.run(engine.execute(definition, workflow_run, **kwargs))  # type: ignore[arg-type]


def test_success_observes_each_actual_executor_attempt_in_lifecycle_order() -> None:
    timeline: list[str] = []
    executor = ScriptedExecutor(timeline)
    observer = RecordingObserver(timeline)
    workflow_run = run()

    returned = execute(WorkflowEngine(executor, observer=observer), linear_workflow(), workflow_run)

    assert returned.status is WorkflowRunStatus.COMPLETED
    assert executor.calls == ["start", "value", "end"]
    assert timeline[:3] == ["start:start", "execute:start", "complete"]
    assert len(observer.completed) == 3
    assert observer.completed[0][0] is observer.contexts["start"]
    assert observer.completed[0][1].output == {}


def test_completion_observation_happens_before_durable_node_persistence() -> None:
    timeline: list[str] = []
    executor = ScriptedExecutor(timeline)
    observer = RecordingObserver(timeline)

    execute(
        WorkflowEngine(executor, observer=observer),
        linear_workflow(),
        run(),
        persistence=TimelinePersistence(timeline),
    )

    assert timeline.index("complete") < timeline.index("persist_complete")


def test_executor_failure_observes_error_and_preserves_workflow_run_failure() -> None:
    timeline: list[str] = []
    executor = ScriptedExecutor(timeline, fail_node="value")
    observer = RecordingObserver(timeline)
    workflow_run = run()

    execute(WorkflowEngine(executor, observer=observer), linear_workflow(), workflow_run)

    assert timeline[-3:] == ["start:value", "execute:value", "fail"]
    assert len(observer.failed) == 1
    context, error, metadata = observer.failed[0]
    assert context is observer.contexts["value"]
    assert (error.code, error.message, metadata) == ("node_execution_failed", "executor exploded", {})
    assert workflow_run.status is WorkflowRunStatus.FAILED
    assert workflow_run.error is not None
    assert (workflow_run.error.code, workflow_run.error.message, workflow_run.error.node_id) == (
        "node_execution_failed",
        "executor exploded",
        "value",
    )
    assert [context for context, _ in observer.completed] == [observer.contexts["start"]]
    assert observer.interrupted == []


def test_interruption_observes_original_result_before_durable_persistence() -> None:
    timeline: list[str] = []
    executor = ScriptedExecutor(timeline)
    observer = RecordingObserver(timeline)
    workflow_run = run()

    execute(
        WorkflowEngine(executor, observer=observer),
        approval_workflow(),
        workflow_run,
        persistence=TimelinePersistence(timeline),
    )

    assert workflow_run.status is WorkflowRunStatus.PAUSED
    assert len(observer.interrupted) == 1
    assert observer.interrupted[0][0] is observer.contexts["approval"]
    assert observer.interrupted[0][1].outcome is NodeExecutionOutcome.INTERRUPTED
    assert timeline.index("interrupt") < timeline.index("persist_interrupt")
    assert observer.completed and len(observer.completed) == 1


def test_resume_observes_only_the_reexecuted_incomplete_nodes() -> None:
    timeline: list[str] = []
    executor = ScriptedExecutor(timeline)
    observer = RecordingObserver(timeline)
    workflow_run = run()
    workflow_run.start()
    workflow_run.pause()
    checkpoint = WorkflowCheckpoint(
        id=uuid4(),
        run_id=workflow_run.id,
        workflow_revision=1,
        sequence=1,
        completed_node_ids=("start",),
        node_outputs={"start": {}},
        pending_node_id="value",
    )

    asyncio.run(WorkflowEngine(executor, observer=observer).resume(linear_workflow(), workflow_run, checkpoint))

    assert executor.calls == ["value", "end"]
    assert list(observer.contexts) == ["value", "end"]


def test_all_completed_checkpoint_and_invalid_definition_do_not_observe() -> None:
    timeline: list[str] = []
    executor = ScriptedExecutor(timeline)
    observer = RecordingObserver(timeline)
    workflow_run = run()
    workflow_run.start()
    workflow_run.pause()
    checkpoint = WorkflowCheckpoint(
        id=uuid4(),
        run_id=workflow_run.id,
        workflow_revision=1,
        sequence=1,
        completed_node_ids=("start", "value", "end"),
        node_outputs={"start": {}, "value": 100, "end": {"value": 100}},
    )

    asyncio.run(WorkflowEngine(executor, observer=observer).resume(linear_workflow(), workflow_run, checkpoint))
    assert timeline == []

    invalid = workflow(
        (WorkflowNode("start", WorkflowNodeKind.START), WorkflowNode("end", WorkflowNodeKind.END)),
        (WorkflowEdge("cycle", "end", "start"),),
    )
    with pytest.raises(WorkflowExecutionValidationError):
        execute(WorkflowEngine(executor, observer=observer), invalid, run())
    assert timeline == []


@pytest.mark.parametrize("failing_callback", ["start", "complete", "fail", "interrupt"])
def test_observer_callback_failures_are_fail_open(failing_callback: str) -> None:
    timeline: list[str] = []
    observer = RecordingObserver(timeline, raise_on=failing_callback)
    if failing_callback == "fail":
        executor = ScriptedExecutor(timeline, fail_node="value")
        workflow_run = run()
        execute(WorkflowEngine(executor, observer=observer), linear_workflow(), workflow_run)
        assert workflow_run.status is WorkflowRunStatus.FAILED
        assert workflow_run.error is not None
        assert workflow_run.error.message == "executor exploded"
    elif failing_callback == "interrupt":
        workflow_run = run()
        execute(WorkflowEngine(ScriptedExecutor(timeline), observer=observer), approval_workflow(), workflow_run)
        assert workflow_run.status is WorkflowRunStatus.PAUSED
    else:
        workflow_run = run()
        execute(WorkflowEngine(ScriptedExecutor(timeline), observer=observer), linear_workflow(), workflow_run)
        assert workflow_run.status is WorkflowRunStatus.COMPLETED
        if failing_callback == "start":
            assert all(context.step_id is None for context, _ in observer.completed)
