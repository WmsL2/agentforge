"""Tests for deterministic START, VALUE, and END execution."""

import asyncio
from types import MappingProxyType
from uuid import uuid4

from app.services.workflow import (
    DeterministicNodeExecutor,
    NodeExecutionContext,
    WorkflowNode,
    WorkflowNodeKind,
)


def execute(node: WorkflowNode, context: NodeExecutionContext):
    return asyncio.run(DeterministicNodeExecutor().execute(node, context))


def context(**kwargs: object) -> NodeExecutionContext:
    return NodeExecutionContext(
        run_id=uuid4(),
        workflow_input=MappingProxyType(kwargs.get("workflow_input", {})),  # type: ignore[arg-type]
        upstream_outputs=MappingProxyType(kwargs.get("upstream_outputs", {})),  # type: ignore[arg-type]
        node_outputs=MappingProxyType(kwargs.get("node_outputs", {})),  # type: ignore[arg-type]
    )


def test_start_returns_a_shallow_copy_of_workflow_input() -> None:
    workflow_input = {"customer_id": 123}

    result = execute(
        WorkflowNode(id="start", kind=WorkflowNodeKind.START),
        context(workflow_input=workflow_input),
    )

    assert result.output == workflow_input
    assert result.output is not workflow_input
    assert workflow_input == {"customer_id": 123}


def test_value_returns_configured_static_value_or_none() -> None:
    configured = WorkflowNode(id="price", kind=WorkflowNodeKind.VALUE, config={"value": 100})
    missing = WorkflowNode(id="missing", kind=WorkflowNodeKind.VALUE)

    assert execute(configured, context()).output == 100
    assert execute(missing, context()).output is None


def test_end_returns_a_shallow_copy_of_direct_upstream_outputs() -> None:
    upstream_outputs = {"a": 1, "b": {"nested": "value"}}

    result = execute(
        WorkflowNode(id="end", kind=WorkflowNodeKind.END),
        context(upstream_outputs=upstream_outputs),
    )

    assert result.output == upstream_outputs
    assert result.output is not upstream_outputs
