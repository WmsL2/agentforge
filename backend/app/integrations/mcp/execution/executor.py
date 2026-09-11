"""ToolExecutor implementation for already-discovered MCP tools."""

from app.integrations.mcp.client import MCPClient, MCPClientError
from app.services.tool import ToolExecutionError, ToolExecutionRequest, ToolExecutionResult


class MCPToolExecutor:
    """Execute one local tool through its bound MCP remote tool name."""

    def __init__(self, client: MCPClient, remote_name: str) -> None:
        self._client = client
        self._remote_name = remote_name

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """Call the bound remote MCP tool with the request arguments."""
        try:
            result = await self._client.call_tool(self._remote_name, request.arguments)
        except MCPClientError as error:
            raise ToolExecutionError(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            ) from error

        if result.is_error:
            message = (
                f"MCP tool '{self._remote_name}' reported an execution error."
                if result.output is None
                else str(result.output)
            )
            raise ToolExecutionError(
                code="mcp_tool_execution_failed",
                message=message,
                retryable=False,
            )

        return ToolExecutionResult(output=result.output, metadata=result.metadata)
