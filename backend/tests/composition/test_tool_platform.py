"""Tests for Tool Platform application composition."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import pytest

from app.composition import tool_platform
from app.core.config import MCPStdioServerSettings


@pytest.mark.anyio
async def test_open_tool_platform_registers_native_tool_and_enters_mcp_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_servers: list[Sequence[MCPStdioServerSettings]] = []

    @asynccontextmanager
    async def fake_mcp_lifecycle(registry, servers: Sequence[MCPStdioServerSettings]) -> AsyncIterator[None]:
        received_servers.append(servers)
        yield

    monkeypatch.setattr(tool_platform, "open_mcp_tool_registrations", fake_mcp_lifecycle)
    servers = (MCPStdioServerSettings(namespace="github", command="github-server"),)

    async with tool_platform.open_tool_platform(servers) as registry:
        assert registry.resolve("current_datetime").definition.name == "current_datetime"

    assert received_servers == [servers]
