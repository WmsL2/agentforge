"""Tests for the official MCP SDK client adapter."""

from typing import Any

import pytest
from mcp import Client, types
from mcp.server import MCPServer

from app.integrations.mcp import MCPClientError, MCPSDKClientAdapter


class FakeSDKClient:
    """A minimal SDK-shaped client returning official SDK result types."""

    def __init__(
        self,
        pages: list[types.ListToolsResult] | None = None,
        call_result: types.CallToolResult | None = None,
    ) -> None:
        self.pages = pages or []
        self.call_result = call_result or types.CallToolResult(content=[])
        self.received_cursor: list[str | None] = []
        self.received_call: tuple[str, dict[str, Any] | None] | None = None

    async def list_tools(self, *, cursor: str | None = None) -> types.ListToolsResult:
        self.received_cursor.append(cursor)
        return self.pages[len(self.received_cursor) - 1]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> types.CallToolResult:
        self.received_call = (name, arguments)
        return self.call_result


class FailingSDKClient(FakeSDKClient):
    """A client that raises SDK-boundary failures."""

    async def list_tools(self, *, cursor: str | None = None) -> types.ListToolsResult:
        raise RuntimeError("List tools failed.")

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> types.CallToolResult:
        raise RuntimeError("Call tool failed.")


def _tool(name: str, description: str | None = "A tool.") -> types.Tool:
    return types.Tool(name=name, description=description, inputSchema={"type": "object"})


@pytest.mark.anyio
async def test_list_tools_maps_sdk_tools_and_collects_all_pages() -> None:
    client = FakeSDKClient(
        pages=[
            types.ListToolsResult(tools=[_tool("create_issue")], nextCursor="page-2"),
            types.ListToolsResult(tools=[_tool("search_issues", None)]),
        ]
    )

    descriptors = await MCPSDKClientAdapter(client).list_tools()  # type: ignore[arg-type]

    assert [descriptor.name for descriptor in descriptors] == ["create_issue", "search_issues"]
    assert descriptors[0].description == "A tool."
    assert descriptors[1].description == ""
    assert descriptors[0].input_schema == {"type": "object"}
    assert descriptors[0].metadata == {}
    assert client.received_cursor == [None, "page-2"]


@pytest.mark.anyio
async def test_call_tool_prefers_structured_content_and_forwards_plain_dict_arguments() -> None:
    client = FakeSDKClient(
        call_result=types.CallToolResult(
            content=[types.TextContent(text="ignored")],
            structuredContent={"value": 42},
        )
    )

    result = await MCPSDKClientAdapter(client).call_tool("create_issue", {"title": "Bug"})  # type: ignore[arg-type]

    assert result.output == {"value": 42}
    assert client.received_call == ("create_issue", {"title": "Bug"})


@pytest.mark.anyio
async def test_call_tool_normalizes_single_text_and_multiple_sdk_content_blocks() -> None:
    text_client = FakeSDKClient(
        call_result=types.CallToolResult(content=[types.TextContent(text="hello")])
    )
    multiple_client = FakeSDKClient(
        call_result=types.CallToolResult(
            content=[types.TextContent(text="one"), types.TextContent(text="two")]
        )
    )

    text_result = await MCPSDKClientAdapter(text_client).call_tool("read", {})  # type: ignore[arg-type]
    multiple_result = await MCPSDKClientAdapter(multiple_client).call_tool("read", {})  # type: ignore[arg-type]

    assert text_result.output == "hello"
    assert multiple_result.output == [
        {"type": "text", "text": "one", "annotations": None, "_meta": None},
        {"type": "text", "text": "two", "annotations": None, "_meta": None},
    ]


@pytest.mark.anyio
async def test_call_tool_preserves_remote_tool_errors_as_results() -> None:
    client = FakeSDKClient(
        call_result=types.CallToolResult(content=[types.TextContent(text="failed")], isError=True)
    )

    result = await MCPSDKClientAdapter(client).call_tool("create_issue", {})  # type: ignore[arg-type]

    assert result.output == "failed"
    assert result.is_error is True


@pytest.mark.anyio
async def test_sdk_exceptions_become_client_errors_with_causes() -> None:
    adapter = MCPSDKClientAdapter(FailingSDKClient())  # type: ignore[arg-type]

    with pytest.raises(MCPClientError) as list_error:
        await adapter.list_tools()
    with pytest.raises(MCPClientError) as call_error:
        await adapter.call_tool("create_issue", {})

    assert list_error.value.code == "mcp_list_tools_failed"
    assert isinstance(list_error.value.__cause__, RuntimeError)
    assert call_error.value.code == "mcp_call_tool_failed"
    assert isinstance(call_error.value.__cause__, RuntimeError)


@pytest.mark.anyio
async def test_adapter_works_with_an_official_in_memory_server() -> None:
    server = MCPServer("test-server")

    @server.tool()
    def multiply(left: int, right: int) -> dict[str, int]:
        """Multiply two integers."""
        return {"value": left * right}

    async with Client(server) as sdk_client:
        adapter = MCPSDKClientAdapter(sdk_client)
        descriptors = await adapter.list_tools()
        result = await adapter.call_tool("multiply", {"left": 6, "right": 7})

    assert descriptors[0].name == "multiply"
    assert descriptors[0].input_schema["type"] == "object"
    assert result.output == {"value": 42}
