"""Deterministic, sequential execution for valid workflow definitions."""

from __future__ import annotations

from app.services.workflow.domain import WorkflowDefinition, WorkflowNodeKind
from app.services.workflow.executor import NodeExecutionContext, NodeExecutor
from app.services.workflow.run_domain import WorkflowRun, WorkflowRunError
from app.services.workflow.validator import WorkflowValidationResult, WorkflowValidator


class WorkflowExecutionValidationError(ValueError):
    """Raised when a definition cannot be executed structurally."""

    def __init__(self, validation_result: WorkflowValidationResult):
        self.validation_result = validation_result
        super().__init__("Workflow definition is invalid for execution.")


class WorkflowEngine:
    """Run validated DAGs in declaration order through a node executor."""

    def __init__(self, executor: NodeExecutor):
        self._executor = executor

    async def execute(self, definition: WorkflowDefinition, run: WorkflowRun) -> WorkflowRun:
        validation_result = WorkflowValidator().validate(definition)
        if not validation_result.is_valid:
            raise WorkflowExecutionValidationError(validation_result)

        run.start()
        workflow_input = dict(run.input)
        predecessors = {node.id: [] for node in definition.nodes}
        for edge in definition.edges:
            predecessors[edge.target].append(edge.source)

        completed: set[str] = set()
        while len(completed) < len(definition.nodes):
            ready_node = next(
                (
                    node
                    for node in definition.nodes
                    if node.id not in completed
                    and all(source in completed for source in predecessors[node.id])
                ),
                None,
            )
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
            try:
                result = await self._executor.execute(ready_node, context)
            except Exception as exception:
                message = str(exception) or type(exception).__name__
                run.fail(
                    WorkflowRunError(
                        code="node_execution_failed",
                        message=message,
                        node_id=ready_node.id,
                    )
                )
                return run

            run.node_outputs[ready_node.id] = result.output
            completed.add(ready_node.id)

        final_output = {
            node.id: run.node_outputs[node.id]
            for node in definition.nodes
            if node.kind is WorkflowNodeKind.END
        }
        run.complete(final_output)
        return run
