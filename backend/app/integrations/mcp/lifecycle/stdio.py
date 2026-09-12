"""Application-scoped lifecycle for stdio MCP tool registrations."""

from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager

from app.core.config import MCPStdioServerSettings
from app.integrations.mcp.registration import MCPToolRegistrationService
from app.integrations.mcp.transport import open_stdio_mcp_client
from app.services.tool import ToolRegistry


@asynccontextmanager
async def open_mcp_tool_registrations(
    registry: ToolRegistry,
    servers: Sequence[MCPStdioServerSettings],
) -> AsyncIterator[None]:
    """Keep configured stdio MCP clients alive while their tools are registered."""
    registration_service = MCPToolRegistrationService()
    async with AsyncExitStack() as stack:
        for server in servers:
            client = await stack.enter_async_context(
                open_stdio_mcp_client(
                    command=server.command,
                    args=server.args,
                    env=server.env,
                )
            )
            await registration_service.register(
                registry=registry,
                client=client,
                namespace=server.namespace,
            )
        yield
