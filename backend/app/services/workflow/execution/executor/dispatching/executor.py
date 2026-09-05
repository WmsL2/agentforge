"""Dispatch workflow nodes to their responsible executors."""

from app.services.workflow.definition.model.domain import WorkflowNode, WorkflowNodeKind
from app.services.workflow.execution.executor.contract import (
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutor,
)


class DispatchingNodeExecutor:
    """Delegate each supported workflow node kind to its node executor."""

    def __init__(
        self,
        deterministic_executor: NodeExecutor,
        agent_executor: NodeExecutor,
    ) -> None:
        self._deterministic_executor = deterministic_executor
        self._agent_executor = agent_executor

    async def execute(
        self,
        node: WorkflowNode,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        if node.kind in {
            WorkflowNodeKind.START,
            WorkflowNodeKind.VALUE,
            WorkflowNodeKind.END,
        }:
            return await self._deterministic_executor.execute(node, context)
        if node.kind is WorkflowNodeKind.AGENT:
            return await self._agent_executor.execute(node, context)
        raise RuntimeError(f"Unsupported workflow node kind: {node.kind}")
