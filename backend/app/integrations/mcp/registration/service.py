"""Registration of discovered MCP tools into the Tool Platform."""

from app.integrations.mcp.client import MCPClient
from app.integrations.mcp.discovery import MCPToolDiscovery
from app.integrations.mcp.execution import MCPToolExecutor
from app.services.tool import ToolRegistration, ToolRegistry


class MCPToolRegistrationService:
    """Discover MCP tools and register bound executors in a ToolRegistry."""

    def __init__(self, discovery: MCPToolDiscovery | None = None) -> None:
        self._discovery = discovery or MCPToolDiscovery()

    async def register(
        self,
        registry: ToolRegistry,
        client: MCPClient,
        namespace: str,
    ) -> tuple[ToolRegistration, ...]:
        """Discover and register all tools exposed by one MCP client."""
        discovered_tools = await self._discovery.discover(client, namespace)
        return tuple(
            registry.register(
                discovered.definition,
                MCPToolExecutor(client=client, remote_name=discovered.remote_name),
            )
            for discovered in discovered_tools
        )
