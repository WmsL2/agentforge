"""Offline stdio MCP server fixture for AgentForge integration tests."""

import os

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("agentforge-integration-test")


@mcp.tool()
def multiply(left: int, right: int) -> dict[str, int]:
    """Multiply two integers."""
    return {"value": left * right}


@mcp.tool(structured_output=False)
def read_env(name: str) -> str:
    """Read one environment variable."""
    return os.environ.get(name, "")


@mcp.tool()
def always_fail(message: str) -> str:
    """Fail with the supplied message."""
    raise ToolError(message)


if __name__ == "__main__":
    mcp.run()
