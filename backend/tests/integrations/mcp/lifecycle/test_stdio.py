"""Tests for the application-scoped stdio MCP lifecycle."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.core.config import MCPStdioServerSettings
from app.integrations.mcp import MCPToolCallResult, MCPToolDescriptor
from app.integrations.mcp.lifecycle import open_mcp_tool_registrations
from app.integrations.mcp.lifecycle import stdio as lifecycle_stdio
from app.services.tool import ToolRegistry


class FakeMCPClient:
    """A structural MCP client with one descriptor."""

    def __init__(self, descriptor: MCPToolDescriptor) -> None:
        self.descriptor = descriptor

    async def list_tools(self) -> tuple[MCPToolDescriptor, ...]:
        return (self.descriptor,)

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallResult:
        return MCPToolCallResult()


def _server(namespace: str, command: str) -> MCPStdioServerSettings:
    return MCPStdioServerSettings(
        namespace=namespace,
        command=command,
        args=["--serve"],
        env={"SERVER": namespace},
    )


@pytest.mark.anyio
async def test_lifecycle_registers_multiple_servers_and_closes_all_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str, list[str], dict[str, str] | None]] = []

    @asynccontextmanager
    async def fake_open(command: str, args: list[str], env: dict[str, str] | None) -> AsyncIterator[FakeMCPClient]:
        namespace = "github" if command == "github-server" else "linear"
        events.append(("open", command, args, env))
        try:
            yield FakeMCPClient(
                MCPToolDescriptor(namespace + "_tool", "A tool.", {"type": "object"})
            )
        finally:
            events.append(("close", command, [], None))

    monkeypatch.setattr(lifecycle_stdio, "open_stdio_mcp_client", fake_open)
    registry = ToolRegistry()
    servers = (_server("github", "github-server"), _server("linear", "linear-server"))

    async with open_mcp_tool_registrations(registry, servers):
        assert [definition.name for definition in registry.definitions()] == [
            "github__github_tool",
            "linear__linear_tool",
        ]
        assert [event[0] for event in events] == ["open", "open"]

    assert [event[0] for event in events] == ["open", "open", "close", "close"]
    assert events[0] == ("open", "github-server", ["--serve"], {"SERVER": "github"})
    assert events[1] == ("open", "linear-server", ["--serve"], {"SERVER": "linear"})


@pytest.mark.anyio
async def test_lifecycle_leaves_registry_unchanged_for_no_servers() -> None:
    registry = ToolRegistry()

    async with open_mcp_tool_registrations(registry, ()):
        assert registry.definitions() == ()


@pytest.mark.anyio
async def test_lifecycle_closes_prior_server_when_a_later_server_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def fake_open(command: str, args: list[str], env: dict[str, str] | None) -> AsyncIterator[FakeMCPClient]:
        if command == "broken-server":
            raise RuntimeError("second server failed")
        events.append("first-open")
        try:
            yield FakeMCPClient(MCPToolDescriptor("tool", "A tool.", {"type": "object"}))
        finally:
            events.append("first-close")

    monkeypatch.setattr(lifecycle_stdio, "open_stdio_mcp_client", fake_open)

    with pytest.raises(RuntimeError, match="second server failed"):
        async with open_mcp_tool_registrations(
            ToolRegistry(),
            (_server("first", "first-server"), _server("broken", "broken-server")),
        ):
            pass

    assert events == ["first-open", "first-close"]
