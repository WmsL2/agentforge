"""Framework-independent MCP client contracts."""

from app.integrations.mcp.client.contract import MCPClient
from app.integrations.mcp.client.domain import (
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
