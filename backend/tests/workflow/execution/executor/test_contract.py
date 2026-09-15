"""Tests for the node-execution boundary contracts."""

import asyncio
from types import MappingProxyType
from uuid import uuid4

import pytest

from app.services.workflow import (
    NodeExecutionContext,
    NodeExecutionInterrupt,
    NodeExecutionOutcome,
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


def test_node_execution_result_defaults_to_completed() -> None:
    assert NodeExecutionResult().outcome is NodeExecutionOutcome.COMPLETED


def test_completed_result_rejects_an_interrupt() -> None:
    with pytest.raises(ValueError):
        NodeExecutionResult(interrupt=NodeExecutionInterrupt(type="approval_required", payload={}))


def test_interrupted_result_requires_interrupt_without_output() -> None:
    with pytest.raises(ValueError):
        NodeExecutionResult(outcome=NodeExecutionOutcome.INTERRUPTED)
    with pytest.raises(ValueError):
        NodeExecutionResult(
            output="unexpected",
            outcome=NodeExecutionOutcome.INTERRUPTED,
            interrupt=NodeExecutionInterrupt(type="approval_required", payload={}),
        )


def test_interrupted_result_and_interrupt_payload_are_valid_and_immutable() -> None:
    payload = {"node_id": "approval"}
    interrupt = NodeExecutionInterrupt(type="approval_required", payload=payload)
    result = NodeExecutionResult(outcome=NodeExecutionOutcome.INTERRUPTED, interrupt=interrupt)
    payload["node_id"] = "changed"

    assert result.output is None
    assert result.interrupt is interrupt
    assert result.interrupt.payload == {"node_id": "approval"}


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
