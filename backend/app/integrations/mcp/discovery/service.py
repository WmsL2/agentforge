"""MCP tool discovery and Tool Platform mapping service."""

from app.integrations.mcp.client import MCPClient
from app.integrations.mcp.discovery.domain import MCPDiscoveredTool, MCPToolDiscoveryError
from app.services.tool import ToolDefinition
from app.services.tool.definition.validation import ToolSchemaValidator


class MCPToolDiscovery:
    """Discover MCP tools and map them to local Tool Platform definitions."""

    def __init__(self) -> None:
        self._validator = ToolSchemaValidator()

    async def discover(
        self,
        client: MCPClient,
        namespace: str,
    ) -> tuple[MCPDiscoveredTool, ...]:
        """Return the client's tools with deterministic local names."""
        self._validate_namespace(namespace)
        descriptors = await client.list_tools()
        discovered_tools: list[MCPDiscoveredTool] = []
        local_names: set[str] = set()

        for descriptor in descriptors:
            local_name = f"{namespace}__{descriptor.name}"
            if local_name in local_names:
                raise MCPToolDiscoveryError(
                    "duplicate_tool_name",
                    f"Duplicate discovered tool name: {local_name}.",
                    tool_name=descriptor.name,
                )

            definition = ToolDefinition(
                name=local_name,
                description=descriptor.description,
                input_schema=descriptor.input_schema,
                metadata=descriptor.metadata,
            )
            validation_result = self._validator.validate_schema(definition)
            if not validation_result.is_valid:
                issue = validation_result.issues[0]
                raise MCPToolDiscoveryError(
                    "invalid_tool_schema",
                    f"Invalid schema for remote tool {descriptor.name}: {issue.message}",
                    tool_name=descriptor.name,
                )

            local_names.add(local_name)
            discovered_tools.append(
                MCPDiscoveredTool(remote_name=descriptor.name, definition=definition)
            )

        return tuple(discovered_tools)

    @staticmethod
    def _validate_namespace(namespace: str) -> None:
        """Reject empty and whitespace-padded local namespace configuration."""
        if not namespace or namespace != namespace.strip():
            raise MCPToolDiscoveryError(
                "invalid_namespace",
                "MCP tool namespace must be non-empty and contain no surrounding whitespace.",
            )
