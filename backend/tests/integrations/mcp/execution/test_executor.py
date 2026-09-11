"""Tests for MCPToolExecutor."""

from collections.abc import Mapping
from typing import Any

import pytest

from app.integrations.mcp import MCPClientError, MCPToolCallResult, MCPToolExecutor
from app.integrations.mcp.execution import MCPToolExecutor as ExecutionPackageMCPToolExecutor
from app.services.tool import (
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutor,
)


class FakeMCPClient:
    """A structural MCP client that records a single tool invocation."""

    def __init__(self, result: MCPToolCallResult | None = None) -> None:
        self.result = result or MCPToolCallResult()
        self.received_tool_name: str | None = None
        self.received_arguments: Mapping[str, Any] | None = None

    async def list_tools(self) -> tuple[()]:
        return ()

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallResult:
        self.received_tool_name = tool_name
        self.received_arguments = arguments
        return self.result


class FailingMCPClient(FakeMCPClient):
    """A client that fails at the MCP client boundary."""

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallResult:
        raise MCPClientError("mcp_transport_failed", "Connection lost.", retryable=True)


async def _execute(executor: ToolExecutor, request: ToolExecutionRequest) -> ToolExecutionResult:
    return await executor.execute(request)


@pytest.mark.anyio
async def test_execute_uses_bound_remote_name_and_forwards_only_arguments() -> None:
    client = FakeMCPClient(MCPToolCallResult(output={"issue": 42}))
    request = ToolExecutionRequest(
        tool_name="github__create_issue",
        arguments={"title": "Bug"},
        metadata={"source": "agent"},
    )

    result = await _execute(MCPToolExecutor(client, remote_name="create_issue"), request)

    assert client.received_tool_name == "create_issue"
    assert client.received_arguments is request.arguments
    assert client.received_arguments == {"title": "Bug"}
    assert result.output == {"issue": 42}


@pytest.mark.anyio
async def test_execute_preserves_successful_result_metadata() -> None:
    client = FakeMCPClient(
        MCPToolCallResult(output={"issue": 42}, metadata={"request_id": "abc"})
    )

    result = await MCPToolExecutor(client, remote_name="create_issue").execute(
        ToolExecutionRequest(tool_name="github__create_issue")
    )

    assert result.output == {"issue": 42}
    assert result.metadata == {"request_id": "abc"}


@pytest.mark.anyio
async def test_execute_translates_client_error_and_preserves_cause() -> None:
    with pytest.raises(ToolExecutionError) as error_info:
        await MCPToolExecutor(FailingMCPClient(), remote_name="create_issue").execute(
            ToolExecutionRequest(tool_name="github__create_issue")
        )

    assert error_info.value.code == "mcp_transport_failed"
    assert error_info.value.message == "Connection lost."
    assert error_info.value.retryable is True
    assert isinstance(error_info.value.__cause__, MCPClientError)


@pytest.mark.anyio
async def test_execute_raises_for_remote_tool_error() -> None:
    client = FakeMCPClient(MCPToolCallResult(output="Remote execution failed.", is_error=True))

    with pytest.raises(ToolExecutionError) as error_info:
        await MCPToolExecutor(client, remote_name="create_issue").execute(
            ToolExecutionRequest(tool_name="github__create_issue")
        )

    assert error_info.value.code == "mcp_tool_execution_failed"
    assert error_info.value.message == "Remote execution failed."
    assert error_info.value.retryable is False


@pytest.mark.anyio
async def test_execute_raises_descriptive_error_for_remote_error_without_output() -> None:
    client = FakeMCPClient(MCPToolCallResult(is_error=True))

    with pytest.raises(ToolExecutionError) as error_info:
        await MCPToolExecutor(client, remote_name="create_issue").execute(
            ToolExecutionRequest(tool_name="github__create_issue")
        )

    assert error_info.value.code == "mcp_tool_execution_failed"
    assert "create_issue" in error_info.value.message
    assert error_info.value.retryable is False


def test_executor_is_exported_from_mcp_and_execution_packages() -> None:
    assert ExecutionPackageMCPToolExecutor is MCPToolExecutor
