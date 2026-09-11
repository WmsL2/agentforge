"""Public contracts for the MCP integration boundary."""

from app.integrations.mcp.client import (
    MCPClient,
    MCPClientError,
    MCPToolCallResult,
    MCPToolDescriptor,
)

__all__ = [
    "MCPClient",
    "MCPClientError",
    "MCPToolCallResult",
    "MCPToolDescriptor",
]
