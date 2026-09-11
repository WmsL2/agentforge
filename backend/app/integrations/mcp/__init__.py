"""Public contracts for the MCP integration boundary."""

from app.integrations.mcp.client import (
    MCPClient,
    MCPClientError,
    MCPSDKClientAdapter,
    MCPToolCallResult,
    MCPToolDescriptor,
)
from app.integrations.mcp.discovery import (
    MCPDiscoveredTool,
    MCPToolDiscovery,
    MCPToolDiscoveryError,
)
from app.integrations.mcp.execution import MCPToolExecutor
from app.integrations.mcp.transport import open_stdio_mcp_client

__all__ = [
    "MCPClient",
    "MCPClientError",
    "MCPDiscoveredTool",
    "MCPSDKClientAdapter",
    "MCPToolCallResult",
    "MCPToolDescriptor",
    "MCPToolDiscovery",
    "MCPToolDiscoveryError",
    "MCPToolExecutor",
    "open_stdio_mcp_client",
]
