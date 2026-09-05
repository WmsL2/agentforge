"""Tests for workflow node-kind dispatching."""

import asyncio
from uuid import uuid4

import pytest

from app.services.workflow import (
    DispatchingNodeExecutor,
    NodeExecutionContext,
    NodeExecutionResult,
    WorkflowNode,
    WorkflowNodeKind,
)


class SpyExecutor:
    def __init__(self, output: str) -> None:
        self.calls: list[tuple[WorkflowNode, NodeExecutionContext]] = []
        self._output = output

    async def execute(
        self,
        node: WorkflowNode,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        self.calls.append((node, context))
        return NodeExecutionResult(output=self._output)


def context() -> NodeExecutionContext:
    return NodeExecutionContext(
        run_id=uuid4(), workflow_input={}, upstream_outputs={}, node_outputs={}
    )


@pytest.mark.parametrize(
    "kind",
    [WorkflowNodeKind.START, WorkflowNodeKind.VALUE, WorkflowNodeKind.END],
)
def test_dispatches_deterministic_node_kinds_to_deterministic_executor(
    kind: WorkflowNodeKind,
) -> None:
    deterministic = SpyExecutor("deterministic")
    agent = SpyExecutor("agent")
    executor = DispatchingNodeExecutor(deterministic, agent)
    workflow_node = WorkflowNode(id=kind.value, kind=kind)
    execution_context = context()

    result = asyncio.run(executor.execute(workflow_node, execution_context))

    assert result.output == "deterministic"
    assert deterministic.calls == [(workflow_node, execution_context)]
    assert agent.calls == []


def test_dispatches_agent_nodes_to_agent_executor() -> None:
    deterministic = SpyExecutor("deterministic")
    agent = SpyExecutor("agent")
    executor = DispatchingNodeExecutor(deterministic, agent)
    workflow_node = WorkflowNode(id="agent", kind=WorkflowNodeKind.AGENT)
    execution_context = context()

    result = asyncio.run(executor.execute(workflow_node, execution_context))

    assert result.output == "agent"
    assert deterministic.calls == []
    assert agent.calls == [(workflow_node, execution_context)]
