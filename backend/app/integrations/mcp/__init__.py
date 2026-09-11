"""Public contracts for the MCP integration boundary."""

from app.integrations.mcp.client import (
    MCPClient,
    MCPClientError,
    MCPToolCallResult,
    MCPToolDescriptor,
)
from app.integrations.mcp.discovery import (
    MCPDiscoveredTool,
    MCPToolDiscovery,
    MCPToolDiscoveryError,
)

__all__ = [
    "MCPClient",
    "MCPClientError",
    "MCPDiscoveredTool",
    "MCPToolCallResult",
    "MCPToolDescriptor",
    "MCPToolDiscovery",
    "MCPToolDiscoveryError",
]
