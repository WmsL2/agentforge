"""Official MCP SDK adapter for AgentForge client contracts."""

from collections.abc import Mapping
from typing import Any

from mcp import Client
from mcp.types import TextContent

from app.integrations.mcp.client.domain import (
    MCPClientError,
    MCPToolCallResult,
    MCPToolDescriptor,
)


class MCPSDKClientAdapter:
    """Adapt an entered official MCP SDK client to AgentForge contracts."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def list_tools(self) -> tuple[MCPToolDescriptor, ...]:
        """Return a complete, ordered snapshot of the SDK client's tools."""
        cursor: str | None = None
        descriptors: list[MCPToolDescriptor] = []

        try:
            while True:
                page = await self._client.list_tools(cursor=cursor)
                descriptors.extend(
                    MCPToolDescriptor(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.input_schema,
                    )
                    for tool in page.tools
                )
                if page.next_cursor is None:
                    return tuple(descriptors)
                cursor = page.next_cursor
        except Exception as error:
            raise MCPClientError(
                code="mcp_list_tools_failed",
                message=str(error) or type(error).__name__,
            ) from error

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallResult:
        """Call one remote MCP tool and normalize the SDK result."""
        try:
            result = await self._client.call_tool(tool_name, dict(arguments))
        except Exception as error:
            raise MCPClientError(
                code="mcp_call_tool_failed",
                message=str(error) or type(error).__name__,
            ) from error

        return MCPToolCallResult(
            output=self._normalize_output(result.structured_content, result.content),
            is_error=result.is_error,
        )

    @staticmethod
    def _normalize_output(structured_content: Any, content: list[Any]) -> Any:
        """Convert SDK content into plain application-owned Python values."""
        if structured_content is not None:
            return structured_content
        if len(content) == 1 and isinstance(content[0], TextContent):
            return content[0].text
        return [block.model_dump(mode="json", by_alias=True) for block in content]
