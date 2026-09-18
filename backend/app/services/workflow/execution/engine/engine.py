"""Deterministic, sequential execution for valid workflow definitions."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from uuid import UUID

from app.services.workflow.definition.model.domain import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowNodeKind,
)
from app.services.workflow.definition.validation.validator import (
    WorkflowValidationResult,
    WorkflowValidator,
)
from app.services.workflow.execution.checkpoint.domain import WorkflowCheckpoint
from app.services.workflow.execution.engine.persistence import WorkflowExecutionPersistence
from app.services.workflow.execution.executor.contract import (
    NodeExecutionContext,
    NodeExecutionOutcome,
    NodeExecutionResult,
    NodeExecutor,
)
from app.services.workflow.execution.observability.domain import RunStepError
from app.services.workflow.execution.observability.observer.contract import (
    WorkflowExecutionObserver,
    WorkflowObservationContext,
)
from app.services.workflow.execution.observability.observer.noop import (
    NoOpWorkflowExecutionObserver,
)
from app.services.workflow.execution.run.domain import (
    WorkflowRun,
    WorkflowRunError,
    WorkflowRunStatus,
    WorkflowRunTransitionError,
)


class WorkflowExecutionValidationError(ValueError):
    """Raised when a definition cannot be executed structurally."""

    def __init__(self, validation_result: WorkflowValidationResult):
        self.validation_result = validation_result
        super().__init__("Workflow definition is invalid for execution.")


class WorkflowResumeValidationError(ValueError):
    """Raised when a checkpoint cannot safely resume a workflow run."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Workflow checkpoint cannot resume this run: {code}.")


class WorkflowEngine:
    """Run validated DAGs in declaration order through a node executor."""

    def __init__(
        self,
        executor: NodeExecutor,
        *,
        observer: WorkflowExecutionObserver | None = None,
    ):
        self._executor = executor
        self._observer = observer or NoOpWorkflowExecutionObserver()

    async def execute(
        self,
        definition: WorkflowDefinition,
        run: WorkflowRun,
        *,
        persistence: WorkflowExecutionPersistence | None = None,
    ) -> WorkflowRun:
        self.validate_definition(definition)
        run.start()
        return await self._run_from_state(definition, run, completed=set(), persistence=persistence)

    async def resume(
        self,
        definition: WorkflowDefinition,
        run: WorkflowRun,
        checkpoint: WorkflowCheckpoint,
        *,
        persistence: WorkflowExecutionPersistence | None = None,
    ) -> WorkflowRun:
        """Resume a paused run from one validated immutable checkpoint."""
        predecessors = self.validate_resume(definition, run, checkpoint)

        run.node_outputs = dict(checkpoint.node_outputs)
        run.resume()
        return await self._run_from_state(
            definition,
            run,
            completed=set(checkpoint.completed_node_ids),
            first_node_id=checkpoint.pending_node_id,
            predecessors=predecessors,
            persistence=persistence,
        )

    def validate_resume(
        self,
        definition: WorkflowDefinition,
        run: WorkflowRun,
        checkpoint: WorkflowCheckpoint,
    ) -> dict[str, list[str]]:
        """Purely validate a paused run and checkpoint before resuming it."""
        self.validate_definition(definition)
        if run.status is not WorkflowRunStatus.PAUSED:
            raise WorkflowRunTransitionError(run.status, WorkflowRunStatus.RUNNING)
        predecessors = self._build_predecessors(definition)
        self._validate_resume_state(definition, run, checkpoint, predecessors)
        return predecessors

    def validate_definition(self, definition: WorkflowDefinition) -> None:
        """Reject structurally invalid definitions before execution persistence begins."""
        validation_result = WorkflowValidator().validate(definition)
        if not validation_result.is_valid:
            raise WorkflowExecutionValidationError(validation_result)

    @staticmethod
    def _build_predecessors(definition: WorkflowDefinition) -> dict[str, list[str]]:
        predecessors = {node.id: [] for node in definition.nodes}
        for edge in definition.edges:
            predecessors[edge.target].append(edge.source)
        return predecessors

    @staticmethod
    def _validate_resume_state(
        definition: WorkflowDefinition,
        run: WorkflowRun,
        checkpoint: WorkflowCheckpoint,
        predecessors: dict[str, list[str]],
    ) -> None:
        if checkpoint.run_id != run.id:
            raise WorkflowResumeValidationError("checkpoint_run_mismatch")
        if checkpoint.workflow_revision != run.workflow_revision:
            raise WorkflowResumeValidationError("checkpoint_revision_mismatch")

        node_ids = {node.id for node in definition.nodes}
        completed = set(checkpoint.completed_node_ids)
        if not completed <= node_ids:
            raise WorkflowResumeValidationError("checkpoint_unknown_completed_node")
        if set(checkpoint.node_outputs) != completed:
            raise WorkflowResumeValidationError("checkpoint_output_mismatch")
        if any(not set(predecessors[node_id]) <= completed for node_id in completed):
            raise WorkflowResumeValidationError("checkpoint_dependency_incomplete")

        pending_node_id = checkpoint.pending_node_id
        if pending_node_id is not None:
            if pending_node_id not in node_ids:
                raise WorkflowResumeValidationError("checkpoint_unknown_pending_node")
            if not set(predecessors[pending_node_id]) <= completed:
                raise WorkflowResumeValidationError("checkpoint_pending_not_ready")

    async def _run_from_state(
        self,
        definition: WorkflowDefinition,
        run: WorkflowRun,
        *,
        completed: set[str],
        first_node_id: str | None = None,
        predecessors: dict[str, list[str]] | None = None,
        persistence: WorkflowExecutionPersistence | None = None,
    ) -> WorkflowRun:
        workflow_input = dict(run.input)
        predecessors = predecessors or self._build_predecessors(definition)
        if len(completed) == len(definition.nodes):
            run.complete(
                {
                    node.id: run.node_outputs[node.id]
                    for node in definition.nodes
                    if node.kind is WorkflowNodeKind.END
                }
            )
            return run
        while len(completed) < len(definition.nodes):
            ready_node = self._next_ready_node(
                definition,
                completed,
                predecessors,
                first_node_id,
            )
            first_node_id = None
            if ready_node is None:
                raise RuntimeError("Validated workflow execution made no scheduling progress.")

            upstream_outputs = {
                source: run.node_outputs[source] for source in predecessors[ready_node.id]
            }
            context = NodeExecutionContext(
                run_id=run.id,
                workflow_input=workflow_input,
                upstream_outputs=upstream_outputs,
                node_outputs=run.node_outputs,
            )
            observation_context = await self._start_observation(run.id, ready_node, context)
            context = replace(context, step_id=observation_context.step_id)
            try:
                result = await self._executor.execute(ready_node, context)
            except Exception as exception:
                message = str(exception) or type(exception).__name__
                await self._fail_observation(
                    observation_context,
                    RunStepError(code="node_execution_failed", message=message),
                )
                run.fail(
                    WorkflowRunError(
                        code="node_execution_failed",
                        message=message,
                        node_id=ready_node.id,
                    )
                )
                return run

            if result.outcome is NodeExecutionOutcome.INTERRUPTED:
                interrupt = result.interrupt
                if interrupt is None:
                    raise RuntimeError(
                        "Interrupted node execution result is missing interrupt data."
                    )
                await self._interrupt_observation(observation_context, result)
                run.pause()
                if persistence is not None:
                    await persistence.persist_interruption(
                        run,
                        completed_node_ids=tuple(
                            node.id for node in definition.nodes if node.id in completed
                        ),
                        pending_node_id=ready_node.id,
                        interrupt={"type": interrupt.type, "payload": dict(interrupt.payload)},
                    )
                return run

            await self._complete_observation(observation_context, result)
            run.node_outputs[ready_node.id] = result.output
            completed.add(ready_node.id)
            if len(completed) == len(definition.nodes):
                final_output = {
                    node.id: run.node_outputs[node.id]
                    for node in definition.nodes
                    if node.kind is WorkflowNodeKind.END
                }
                run.complete(final_output)
                pending_node_id = None
            else:
                pending_node = self._next_ready_node(definition, completed, predecessors, None)
                if pending_node is None:
                    raise RuntimeError("Validated workflow execution made no scheduling progress.")
                pending_node_id = pending_node.id

            if persistence is not None:
                await persistence.persist_node_completion(
                    run,
                    completed_node_ids=tuple(
                        node.id for node in definition.nodes if node.id in completed
                    ),
                    pending_node_id=pending_node_id,
                )

            if len(completed) == len(definition.nodes):
                return run

        raise RuntimeError("Validated workflow execution made no scheduling progress.")

    async def _start_observation(
        self,
        run_id: UUID,
        node: WorkflowNode,
        execution_context: NodeExecutionContext,
    ) -> WorkflowObservationContext:
        try:
            return await self._observer.start_step(
                run_id=run_id,
                node=node,
                execution_context=execution_context,
            )
        except Exception:
            return WorkflowObservationContext(run_id=run_id)

    async def _complete_observation(
        self,
        context: WorkflowObservationContext,
        result: NodeExecutionResult,
    ) -> None:
        with suppress(Exception):
            await self._observer.complete_step(context, result=result)

    async def _fail_observation(
        self,
        context: WorkflowObservationContext,
        error: RunStepError,
    ) -> None:
        with suppress(Exception):
            await self._observer.fail_step(context, error=error, metadata={})

    async def _interrupt_observation(
        self,
        context: WorkflowObservationContext,
        result: NodeExecutionResult,
    ) -> None:
        with suppress(Exception):
            await self._observer.interrupt_step(context, result=result)

    @staticmethod
    def _next_ready_node(
        definition: WorkflowDefinition,
        completed: set[str],
        predecessors: dict[str, list[str]],
        first_node_id: str | None,
    ) -> WorkflowNode | None:
        if first_node_id is not None:
            return next(
                (
                    node
                    for node in definition.nodes
                    if node.id == first_node_id
                    and node.id not in completed
                    and all(source in completed for source in predecessors[node.id])
                ),
                None,
            )
        return next(
            (
                node
                for node in definition.nodes
                if node.id not in completed
                and all(source in completed for source in predecessors[node.id])
            ),
            None,
        )
