"""Tests for the node-execution boundary contracts."""

import asyncio
from types import MappingProxyType
from uuid import uuid4

import pytest

from app.services.workflow import (
    NodeExecutionContext,
    NodeExecutionResult,
    WorkflowNode,
    WorkflowNodeKind,
)


class EchoExecutor:
    async def execute(
        self, node: WorkflowNode, context: NodeExecutionContext
    ) -> NodeExecutionResult:
        return NodeExecutionResult(output={"node": node.id, "run": str(context.run_id)})


def test_execution_context_exposes_required_fields() -> None:
    run_id = uuid4()
    context = NodeExecutionContext(
        run_id=run_id,
        workflow_input=MappingProxyType({"request": "hello"}),
        upstream_outputs=MappingProxyType({"start": {"request": "hello"}}),
        node_outputs=MappingProxyType({"start": {"request": "hello"}}),
    )

    assert context.run_id == run_id
    assert context.workflow_input == {"request": "hello"}
    assert context.upstream_outputs == {"start": {"request": "hello"}}
    assert context.node_outputs == {"start": {"request": "hello"}}


def test_node_execution_result_metadata_defaults_are_independent() -> None:
    first = NodeExecutionResult()
    second = NodeExecutionResult()

    first.metadata["attempt"] = 1

    assert second.metadata == {}


def test_async_executor_contract_can_be_implemented() -> None:
    executor = EchoExecutor()
    result = asyncio.run(
        executor.execute(
            WorkflowNode(id="value", kind=WorkflowNodeKind.VALUE),
            NodeExecutionContext(
                run_id=uuid4(),
                workflow_input=MappingProxyType({}),
                upstream_outputs=MappingProxyType({}),
                node_outputs=MappingProxyType({}),
            ),
        )
    )

    assert result.output["node"] == "value"


def test_execution_context_top_level_mappings_can_be_read_only() -> None:
    node_outputs: dict[str, object] = {}
    context = NodeExecutionContext(
        run_id=uuid4(),
        workflow_input={},
        upstream_outputs={},
        node_outputs=node_outputs,
    )

    with pytest.raises(TypeError):
        context.node_outputs["new"] = "value"  # type: ignore[index]
    assert node_outputs == {}
