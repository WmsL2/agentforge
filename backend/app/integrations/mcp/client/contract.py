"""Protocol for framework-independent MCP clients."""

from collections.abc import Mapping
from typing import Any, Protocol

from app.integrations.mcp.client.domain import MCPToolCallResult, MCPToolDescriptor


class MCPClient(Protocol):
    """Discover and invoke MCP server tools asynchronously."""

    async def list_tools(self) -> tuple[MCPToolDescriptor, ...]:
        """Return the tools currently exposed by the MCP server."""

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallResult:
        """Invoke one MCP server tool by its original name."""
