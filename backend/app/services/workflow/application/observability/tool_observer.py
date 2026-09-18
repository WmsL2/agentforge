"""Workflow application adapter translating Tool Platform events to trace events."""

from app.services.tool.execution import (
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from app.services.workflow.execution.observability.domain import TraceEventKind
from app.services.workflow.execution.observability.observer import (
    WorkflowExecutionObserver,
    WorkflowObservationContext,
)


class WorkflowToolExecutionObserver:
    """Record tool facts only when they belong to a concrete workflow run step."""

    def __init__(self, observer: WorkflowExecutionObserver) -> None:
        self._observer = observer

    async def start_tool(self, request: ToolExecutionRequest) -> None:
        await self._record(
            request,
            TraceEventKind.TOOL_STARTED,
            {"tool_name": request.tool_name, "arguments": dict(request.arguments)},
        )

    async def complete_tool(self, request: ToolExecutionRequest, result: ToolExecutionResult) -> None:
        await self._record(
            request,
            TraceEventKind.TOOL_COMPLETED,
            {"tool_name": request.tool_name, "metadata": dict(result.metadata)},
        )

    async def fail_tool(self, request: ToolExecutionRequest, error: ToolExecutionError) -> None:
        await self._record(
            request,
            TraceEventKind.TOOL_FAILED,
            {
                "tool_name": request.tool_name,
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "retryable": error.retryable,
                },
            },
        )

    async def _record(
        self, request: ToolExecutionRequest, kind: TraceEventKind, payload: dict[str, object]
    ) -> None:
        if request.trace_run_id is None or request.trace_step_id is None:
            return None
        await self._observer.record_event(
            WorkflowObservationContext(run_id=request.trace_run_id, step_id=request.trace_step_id),
            kind=kind,
            payload=payload,
        )
