"""Pure domain contracts for MCP tool discovery."""

from dataclasses import dataclass

from app.services.tool import ToolDefinition


@dataclass(frozen=True)
class MCPDiscoveredTool:
    """An MCP tool with separate remote and local execution identities."""

    remote_name: str
    definition: ToolDefinition


class MCPToolDiscoveryError(RuntimeError):
    """A framework-independent error raised while discovering MCP tools."""

    def __init__(self, code: str, message: str, tool_name: str | None = None) -> None:
        self.code = code
        self.message = message
        self.tool_name = tool_name
        super().__init__(message)
