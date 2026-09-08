"""Protocol for framework-independent tool executors."""

from typing import Protocol

from app.services.tool.execution.domain import ToolExecutionRequest, ToolExecutionResult


class ToolExecutor(Protocol):
    """Execute one tool invocation asynchronously."""

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """Execute ``request`` and return its result."""
