"""Small deterministic executor for the initial workflow node kinds."""

from __future__ import annotations

from app.services.workflow.domain import WorkflowNode, WorkflowNodeKind
from app.services.workflow.executor import NodeExecutionContext, NodeExecutionResult


class DeterministicNodeExecutor:
    """Execute START, VALUE, and END nodes without I/O."""

    async def execute(
        self,
        node: WorkflowNode,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        if node.kind is WorkflowNodeKind.START:
            return NodeExecutionResult(output=dict(context.workflow_input))
        if node.kind is WorkflowNodeKind.VALUE:
            return NodeExecutionResult(output=node.config.get("value"))
        if node.kind is WorkflowNodeKind.END:
            return NodeExecutionResult(output=dict(context.upstream_outputs))
        raise RuntimeError(f"Unsupported workflow node kind: {node.kind}")
