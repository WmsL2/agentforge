"""Tests for MCP tool discovery and mapping."""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from app.integrations.mcp import (
    MCPClient,
    MCPClientError,
    MCPDiscoveredTool,
    MCPToolCallResult,
    MCPToolDescriptor,
    MCPToolDiscovery,
    MCPToolDiscoveryError,
)
from app.integrations.mcp.discovery import (
    MCPDiscoveredTool as DiscoveryPackageMCPDiscoveredTool,
)
from app.integrations.mcp.discovery import MCPToolDiscovery as DiscoveryPackageMCPToolDiscovery
from app.integrations.mcp.discovery import (
    MCPToolDiscoveryError as DiscoveryPackageMCPToolDiscoveryError,
)


class FakeMCPClient:
    """A structural MCP client for discovery tests."""

    def __init__(self, descriptors: tuple[MCPToolDescriptor, ...]) -> None:
        self.descriptors = descriptors

    async def list_tools(self) -> tuple[MCPToolDescriptor, ...]:
        return self.descriptors

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallResult:
        return MCPToolCallResult()


class FailingMCPClient(FakeMCPClient):
    """A client whose discovery boundary fails."""

    async def list_tools(self) -> tuple[MCPToolDescriptor, ...]:
        raise MCPClientError("list_tools_failed", "Unable to list tools.")


async def _discover(
    discovery: MCPToolDiscovery,
    client: MCPClient,
    namespace: str,
) -> tuple[MCPDiscoveredTool, ...]:
    return await discovery.discover(client, namespace)


def _descriptor(name: str, input_schema: Mapping[str, Any] | None = None) -> MCPToolDescriptor:
    return MCPToolDescriptor(
        name=name,
        description=f"Description for {name}.",
        input_schema=input_schema or {"type": "object"},
        metadata={"server": "github"},
    )


def test_discover_maps_tools_in_remote_order() -> None:
    client = FakeMCPClient((_descriptor("create_issue"), _descriptor("search_issues")))

    discovered = asyncio.run(_discover(MCPToolDiscovery(), client, "github"))

    assert isinstance(discovered, tuple)
    assert [tool.remote_name for tool in discovered] == ["create_issue", "search_issues"]
    assert [tool.definition.name for tool in discovered] == [
        "github__create_issue",
        "github__search_issues",
    ]
    assert discovered[0].definition.description == "Description for create_issue."
    assert discovered[0].definition.input_schema == {"type": "object"}
    assert discovered[0].definition.metadata == {"server": "github"}


@pytest.mark.parametrize("namespace", ["", "   ", " github "])
def test_discover_rejects_invalid_namespace(namespace: str) -> None:
    client = FakeMCPClient(())

    with pytest.raises(MCPToolDiscoveryError) as error_info:
        asyncio.run(_discover(MCPToolDiscovery(), client, namespace))

    assert error_info.value.code == "invalid_namespace"


def test_discover_rejects_invalid_schema_with_remote_tool_name() -> None:
    client = FakeMCPClient(
        (_descriptor("create_issue", {"type": "not-a-real-json-schema-type"}),)
    )

    with pytest.raises(MCPToolDiscoveryError) as error_info:
        asyncio.run(_discover(MCPToolDiscovery(), client, "github"))

    assert error_info.value.code == "invalid_tool_schema"
    assert error_info.value.tool_name == "create_issue"
    assert "create_issue" in error_info.value.message


def test_discover_rejects_duplicate_local_tool_names() -> None:
    client = FakeMCPClient((_descriptor("search"), _descriptor("search")))

    with pytest.raises(MCPToolDiscoveryError) as error_info:
        asyncio.run(_discover(MCPToolDiscovery(), client, "github"))

    assert error_info.value.code == "duplicate_tool_name"
    assert error_info.value.tool_name == "search"


def test_discover_does_not_normalize_remote_tool_names() -> None:
    client = FakeMCPClient((_descriptor("admin.tools.list"),))

    discovered = asyncio.run(_discover(MCPToolDiscovery(), client, "github"))

    assert discovered[0].remote_name == "admin.tools.list"
    assert discovered[0].definition.name == "github__admin.tools.list"


def test_discover_propagates_client_errors_unchanged() -> None:
    error = MCPClientError("list_tools_failed", "Unable to list tools.")

    with pytest.raises(MCPClientError) as error_info:
        asyncio.run(_discover(MCPToolDiscovery(), FailingMCPClient(()), "github"))

    assert error_info.value.code == error.code
    assert error_info.value.message == error.message


def test_discovery_contracts_are_exported_from_mcp_and_discovery_packages() -> None:
    assert DiscoveryPackageMCPDiscoveredTool is MCPDiscoveredTool
    assert DiscoveryPackageMCPToolDiscovery is MCPToolDiscovery
    assert DiscoveryPackageMCPToolDiscoveryError is MCPToolDiscoveryError
