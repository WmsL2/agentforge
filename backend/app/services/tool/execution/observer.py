"""Framework-independent lifecycle observer for Tool Platform execution."""

from typing import Protocol

from app.services.tool.execution.domain import (
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
)


class ToolExecutionObserver(Protocol):
    async def start_tool(self, request: ToolExecutionRequest) -> None: ...

    async def complete_tool(
        self, request: ToolExecutionRequest, result: ToolExecutionResult
    ) -> None: ...

    async def fail_tool(self, request: ToolExecutionRequest, error: ToolExecutionError) -> None: ...


class NoOpToolExecutionObserver:
    """Observer implementation that preserves standalone Tool Platform behavior."""

    async def start_tool(self, request: ToolExecutionRequest) -> None:
        return None

    async def complete_tool(self, request: ToolExecutionRequest, result: ToolExecutionResult) -> None:
        return None

    async def fail_tool(self, request: ToolExecutionRequest, error: ToolExecutionError) -> None:
        return None
