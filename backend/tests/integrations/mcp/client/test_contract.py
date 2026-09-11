"""Tests for the framework-independent MCPClient protocol."""

import asyncio
from collections.abc import Mapping
from typing import Any

from app.integrations.mcp import MCPClient, MCPToolCallResult, MCPToolDescriptor
from app.integrations.mcp.client import MCPClient as ClientPackageMCPClient


class FakeMCPClient:
    """A structural MCPClient implementation for contract tests."""

    def __init__(self) -> None:
        self.received_tool_name: str | None = None
        self.received_arguments: Mapping[str, Any] | None = None
        self.tools = (
            MCPToolDescriptor(
                name="create_issue",
                description="Create an issue.",
                input_schema={"type": "object"},
            ),
        )

    async def list_tools(self) -> tuple[MCPToolDescriptor, ...]:
        return self.tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallResult:
        self.received_tool_name = tool_name
        self.received_arguments = arguments
        return MCPToolCallResult(output={"accepted": tool_name})


async def _list_tools(client: MCPClient) -> tuple[MCPToolDescriptor, ...]:
    return await client.list_tools()


async def _call_tool(
    client: MCPClient,
    tool_name: str,
    arguments: Mapping[str, Any],
) -> MCPToolCallResult:
    return await client.call_tool(tool_name, arguments)


def test_structural_client_lists_tools_and_receives_call_arguments() -> None:
    client = FakeMCPClient()
    arguments: dict[str, Any] = {"title": "Boundary contract"}

    tools = asyncio.run(_list_tools(client))
    result = asyncio.run(_call_tool(client, "create_issue", arguments))

    assert tools == client.tools
    assert isinstance(tools, tuple)
    assert client.received_tool_name == "create_issue"
    assert client.received_arguments is arguments
    assert result.output == {"accepted": "create_issue"}
    assert result.is_error is False


def test_client_is_exported_from_client_and_mcp_packages() -> None:
    assert ClientPackageMCPClient is MCPClient
