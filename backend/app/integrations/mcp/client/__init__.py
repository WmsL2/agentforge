"""Framework-independent MCP client contracts."""

from app.integrations.mcp.client.contract import MCPClient
from app.integrations.mcp.client.domain import (
    MCPClientError,
    MCPToolCallResult,
    MCPToolDescriptor,
)
from app.integrations.mcp.client.implementations import MCPSDKClientAdapter

__all__ = [
    "MCPClient",
    "MCPClientError",
    "MCPSDKClientAdapter",
    "MCPToolCallResult",
    "MCPToolDescriptor",
]
