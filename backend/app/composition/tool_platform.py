"""Application composition for the Tool Platform and MCP integrations."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from app.agents.utils import get_current_datetime
from app.core.config import MCPStdioServerSettings
from app.integrations.mcp.lifecycle import open_mcp_tool_registrations
from app.services.tool import ToolDefinition, ToolRegistry
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor


@asynccontextmanager
async def open_tool_platform(
    mcp_servers: Sequence[MCPStdioServerSettings],
) -> AsyncIterator[ToolRegistry]:
    """Create the application-scoped registry and keep MCP clients alive."""
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="current_datetime",
            description="Get the current UTC date and time.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        NativeCallableToolExecutor(get_current_datetime),
    )
    async with open_mcp_tool_registrations(registry, mcp_servers):
        yield registry
