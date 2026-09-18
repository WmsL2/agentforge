"""Tool observer lifecycle and workflow adapter tests."""

from uuid import uuid4

import pytest

from app.services.tool import (
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionService,
    ToolRegistry,
)
from app.services.tool.definition.validation import ToolSchemaValidator
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor
from app.services.workflow.application.observability import WorkflowToolExecutionObserver
from app.services.workflow.execution.observability import TraceEventKind


class ToolObserver:
    def __init__(self) -> None:
        self.events = []

    async def start_tool(self, request): self.events.append("start")
    async def complete_tool(self, request, result): self.events.append("complete")
    async def fail_tool(self, request, error): self.events.append(("fail", error))


def service(observer) -> ToolExecutionService:
    registry = ToolRegistry()
    registry.register(ToolDefinition("echo", "Echo", {"type": "object"}), NativeCallableToolExecutor(lambda: "ok"))
    return ToolExecutionService(registry, ToolSchemaValidator(), observer=observer)


@pytest.mark.anyio
async def test_tool_service_observes_success_and_failure_without_changing_errors() -> None:
    observer = ToolObserver()
    assert (await service(observer).execute(ToolExecutionRequest("echo"))).output == "ok"
    assert observer.events == ["start", "complete"]
    with pytest.raises(ToolExecutionError) as error_info:
        await service(observer).execute(ToolExecutionRequest("missing"))
    assert error_info.value.code == "tool_not_found"
    assert observer.events[-1][0] == "fail"


@pytest.mark.anyio
async def test_workflow_tool_adapter_requires_both_trace_ids() -> None:
    recorded = []

    class WorkflowObserver:
        async def record_event(self, context, *, kind, payload):
            recorded.append((context, kind, payload))

    adapter = WorkflowToolExecutionObserver(WorkflowObserver())
    await adapter.start_tool(ToolExecutionRequest("echo"))
    assert recorded == []
    run_id, step_id = uuid4(), uuid4()
    request = ToolExecutionRequest("echo", arguments={"x": 1}, trace_run_id=run_id, trace_step_id=step_id)
    await adapter.start_tool(request)
    await adapter.complete_tool(request, ToolExecutionResult(metadata={"ms": 1}))
    await adapter.fail_tool(request, ToolExecutionError("failed", "boom", True))
    assert [kind for _, kind, _ in recorded] == [
        TraceEventKind.TOOL_STARTED,
        TraceEventKind.TOOL_COMPLETED,
        TraceEventKind.TOOL_FAILED,
    ]
