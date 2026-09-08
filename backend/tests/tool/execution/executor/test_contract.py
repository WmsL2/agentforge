"""Tests for the framework-independent ToolExecutor protocol."""

import asyncio
from typing import Any

from app.services.tool import ToolExecutionRequest, ToolExecutionResult, ToolExecutor
from app.services.tool.execution.executor import ToolExecutor as ExecutorPackageToolExecutor


class FakeToolExecutor:
    """A structural ToolExecutor implementation for contract tests."""

    def __init__(self) -> None:
        self.received_request: ToolExecutionRequest | None = None

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.received_request = request
        return ToolExecutionResult(output={"accepted": request.tool_name})


async def _execute(executor: ToolExecutor, request: ToolExecutionRequest) -> ToolExecutionResult:
    return await executor.execute(request)


def test_structural_executor_receives_the_full_request_and_returns_result() -> None:
    executor = FakeToolExecutor()
    arguments: dict[str, Any] = {"city": "Shanghai"}
    request = ToolExecutionRequest(
        tool_name="weather_lookup",
        arguments=arguments,
        metadata={"source": "workflow"},
    )

    result = asyncio.run(_execute(executor, request))

    assert executor.received_request is request
    assert executor.received_request.tool_name == "weather_lookup"
    assert executor.received_request.arguments == {"city": "Shanghai"}
    assert executor.received_request.metadata == {"source": "workflow"}
    assert result.output == {"accepted": "weather_lookup"}


def test_executor_is_exported_from_executor_and_root_packages() -> None:
    assert ExecutorPackageToolExecutor is ToolExecutor
