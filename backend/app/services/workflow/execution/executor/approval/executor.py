"""Interrupt workflows when a human approval is required."""

from app.services.workflow.definition.model.domain import WorkflowNode, WorkflowNodeKind
from app.services.workflow.execution.executor.contract import (
    NodeExecutionContext,
    NodeExecutionInterrupt,
    NodeExecutionOutcome,
    NodeExecutionResult,
)


class ApprovalNodeExecutor:
    """Translate an APPROVAL node into a durable execution interruption."""

    async def execute(
        self,
        node: WorkflowNode,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        if node.kind is not WorkflowNodeKind.APPROVAL:
            raise RuntimeError("ApprovalNodeExecutor only supports APPROVAL workflow nodes.")
        return NodeExecutionResult(
            outcome=NodeExecutionOutcome.INTERRUPTED,
            interrupt=NodeExecutionInterrupt(
                type="approval_required",
                payload={"node_id": node.id, "prompt": node.config["prompt"]},
            ),
        )
