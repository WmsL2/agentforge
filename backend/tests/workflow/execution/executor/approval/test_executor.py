"""Tests for the APPROVAL node executor."""

import asyncio
from uuid import uuid4

import pytest

from app.services.workflow import (
    ApprovalNodeExecutor,
    NodeExecutionContext,
    NodeExecutionOutcome,
    WorkflowNode,
    WorkflowNodeKind,
)


def context() -> NodeExecutionContext:
    return NodeExecutionContext(run_id=uuid4(), workflow_input={}, upstream_outputs={}, node_outputs={})


def test_approval_node_returns_approval_required_interruption() -> None:
    result = asyncio.run(
        ApprovalNodeExecutor().execute(
            WorkflowNode("approval", WorkflowNodeKind.APPROVAL, {"prompt": "Continue?"}),
            context(),
        )
    )

    assert result.outcome is NodeExecutionOutcome.INTERRUPTED
    assert result.output is None
    assert result.interrupt is not None
    assert result.interrupt.type == "approval_required"
    assert result.interrupt.payload == {"node_id": "approval", "prompt": "Continue?"}


def test_approval_executor_rejects_other_node_kinds() -> None:
    with pytest.raises(RuntimeError, match="only supports APPROVAL"):
        asyncio.run(
            ApprovalNodeExecutor().execute(WorkflowNode("value", WorkflowNodeKind.VALUE), context())
        )
