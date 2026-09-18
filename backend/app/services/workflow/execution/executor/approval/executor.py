"""Interrupt workflows when a human approval is required."""

from contextlib import suppress

from app.services.workflow.definition.model.domain import WorkflowNode, WorkflowNodeKind
from app.services.workflow.execution.executor.contract import (
    NodeExecutionContext,
    NodeExecutionInterrupt,
    NodeExecutionOutcome,
    NodeExecutionResult,
)
from app.services.workflow.execution.observability.domain import TraceEventKind
from app.services.workflow.execution.observability.observer import (
    NoOpWorkflowExecutionObserver,
    WorkflowExecutionObserver,
    WorkflowObservationContext,
)


class ApprovalNodeExecutor:
    """Translate an APPROVAL node into a durable execution interruption."""

    def __init__(self, *, observer: WorkflowExecutionObserver | None = None) -> None:
        self._observer = observer or NoOpWorkflowExecutionObserver()

    async def execute(
        self,
        node: WorkflowNode,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        if node.kind is not WorkflowNodeKind.APPROVAL:
            raise RuntimeError("ApprovalNodeExecutor only supports APPROVAL workflow nodes.")
        if context.step_id is not None:
            with suppress(Exception):
                await self._observer.record_event(
                    WorkflowObservationContext(run_id=context.run_id, step_id=context.step_id),
                    kind=TraceEventKind.APPROVAL_REQUESTED,
                    payload={"node_id": node.id, "prompt": node.config["prompt"]},
                )
        return NodeExecutionResult(
            outcome=NodeExecutionOutcome.INTERRUPTED,
            interrupt=NodeExecutionInterrupt(
                type="approval_required",
                payload={"node_id": node.id, "prompt": node.config["prompt"]},
            ),
        )
