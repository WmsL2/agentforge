"""Tests for the stdio MCP transport lifecycle."""

from typing import Any

import pytest
from mcp import types

from app.integrations.mcp import MCPClientError
from app.integrations.mcp.transport import open_stdio_mcp_client, stdio


class FakeEnteredClient:
    """An SDK-shaped entered client."""

    async def list_tools(self, *, cursor: str | None = None) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> types.CallToolResult:
        return types.CallToolResult(content=[])


class FakeClientContext:
    """A replacement Client context manager that records lifecycle events."""

    def __init__(self, parameters: Any, entered_client: FakeEnteredClient) -> None:
        self.parameters = parameters
        self.entered_client = entered_client
        self.exited = False

    async def __aenter__(self) -> FakeEnteredClient:
        return self.entered_client

    async def __aexit__(self, *args: object) -> None:
        self.exited = True


@pytest.mark.anyio
async def test_open_stdio_client_uses_explicit_parameters_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered_client = FakeEnteredClient()
    contexts: list[FakeClientContext] = []

    def fake_client(parameters: Any) -> FakeClientContext:
        context = FakeClientContext(parameters, entered_client)
        contexts.append(context)
        return context

    monkeypatch.setattr(stdio, "Client", fake_client)

    async with open_stdio_mcp_client("server-command", ("--flag",), {"TOKEN": "value"}) as client:
        assert await client.list_tools() == ()

    assert contexts[0].parameters.command == "server-command"
    assert contexts[0].parameters.args == ["--flag"]
    assert contexts[0].parameters.env == {"TOKEN": "value"}
    assert contexts[0].exited is True


@pytest.mark.anyio
async def test_open_stdio_client_maps_connection_entry_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingContext:
        async def __aenter__(self) -> FakeEnteredClient:
            raise RuntimeError("Connection failed.")

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(stdio, "Client", lambda parameters: FailingContext())

    with pytest.raises(MCPClientError) as error_info:
        async with open_stdio_mcp_client("server-command"):
            pass

    assert error_info.value.code == "mcp_connection_failed"
    assert isinstance(error_info.value.__cause__, RuntimeError)


@pytest.mark.anyio
async def test_open_stdio_client_preserves_business_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = FakeClientContext(Any, FakeEnteredClient())
    monkeypatch.setattr(stdio, "Client", lambda parameters: context)

    with pytest.raises(ValueError, match="business error"):
        async with open_stdio_mcp_client("server-command"):
            raise ValueError("business error")

    assert context.exited is True
