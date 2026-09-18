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

    async def start_tool(self, request):
        self.events.append("start")

    async def complete_tool(self, request, result):
        self.events.append("complete")

    async def fail_tool(self, request, error):
        self.events.append(("fail", error))


class FailingToolObserver(ToolObserver):
    def __init__(self, failing_callback: str) -> None:
        super().__init__()
        self.failing_callback = failing_callback

    async def start_tool(self, request):
        await super().start_tool(request)
        if self.failing_callback == "start":
            raise RuntimeError("start observer failed")

    async def complete_tool(self, request, result):
        await super().complete_tool(request, result)
        if self.failing_callback == "complete":
            raise RuntimeError("complete observer failed")

    async def fail_tool(self, request, error):
        await super().fail_tool(request, error)
        if self.failing_callback == "fail":
            raise RuntimeError("fail observer failed")


class RaisingExecutor:
    async def execute(self, request):
        raise RuntimeError("executor boom")


def service(observer) -> ToolExecutionService:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("echo", "Echo", {"type": "object"}), NativeCallableToolExecutor(lambda: "ok")
    )
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
async def test_start_and_complete_observer_failures_do_not_block_successful_tool_execution() -> (
    None
):
    for callback in ("start", "complete"):
        observer = FailingToolObserver(callback)

        result = await service(observer).execute(ToolExecutionRequest("echo"))

        assert result.output == "ok"
        assert observer.events == ["start", "complete"]


@pytest.mark.anyio
async def test_fail_observer_failure_does_not_replace_the_original_tool_error() -> None:
    observer = FailingToolObserver("fail")

    with pytest.raises(ToolExecutionError) as error_info:
        await service(observer).execute(ToolExecutionRequest("missing"))

    assert error_info.value.code == "tool_not_found"
    assert observer.events == ["start", ("fail", error_info.value)]


@pytest.mark.anyio
async def test_generic_executor_error_is_normalized_and_observed_as_failure() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition("broken", "Broken", {"type": "object"}), RaisingExecutor())
    observer = ToolObserver()

    with pytest.raises(ToolExecutionError) as error_info:
        await ToolExecutionService(registry, ToolSchemaValidator(), observer=observer).execute(
            ToolExecutionRequest("broken")
        )

    assert error_info.value.code == "tool_execution_failed"
    assert error_info.value.message == "executor boom"
    assert error_info.value.retryable is False
    assert observer.events == ["start", ("fail", error_info.value)]


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
    request = ToolExecutionRequest(
        "echo", arguments={"x": 1}, trace_run_id=run_id, trace_step_id=step_id
    )
    await adapter.start_tool(request)
    await adapter.complete_tool(request, ToolExecutionResult(metadata={"ms": 1}))
    await adapter.fail_tool(request, ToolExecutionError("failed", "boom", True))
    assert [kind for _, kind, _ in recorded] == [
        TraceEventKind.TOOL_STARTED,
        TraceEventKind.TOOL_COMPLETED,
        TraceEventKind.TOOL_FAILED,
    ]
