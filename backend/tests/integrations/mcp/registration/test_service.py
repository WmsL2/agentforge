"""Tests for MCP tool registration."""

from collections.abc import Mapping
from typing import Any

import pytest

from app.integrations.mcp import (
    MCPToolCallResult,
    MCPToolDescriptor,
    MCPToolRegistrationService,
)
from app.integrations.mcp.execution import MCPToolExecutor
from app.services.tool import (
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionService,
    ToolRegistry,
    ToolRegistryError,
    ToolRegistryErrorCode,
)
from app.services.tool.definition.validation import ToolSchemaValidator
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor


class FakeMCPClient:
    """A structural MCP client for registration tests."""

    def __init__(self, descriptors: tuple[MCPToolDescriptor, ...]) -> None:
        self.descriptors = descriptors
        self.received_tool_name: str | None = None

    async def list_tools(self) -> tuple[MCPToolDescriptor, ...]:
        return self.descriptors

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallResult:
        self.received_tool_name = tool_name
        return MCPToolCallResult(output={"accepted": arguments})


def _descriptor(name: str) -> MCPToolDescriptor:
    return MCPToolDescriptor(
        name=name,
        description=f"{name} description",
        input_schema={"type": "object"},
    )


@pytest.mark.anyio
async def test_registers_discovered_tools_in_order_with_bound_remote_names() -> None:
    registry = ToolRegistry()
    client = FakeMCPClient((_descriptor("create_issue"), _descriptor("search_issues")))

    registrations = await MCPToolRegistrationService().register(registry, client, "github")

    assert [registration.definition.name for registration in registrations] == [
        "github__create_issue",
        "github__search_issues",
    ]
    assert all(isinstance(registration.executor, MCPToolExecutor) for registration in registrations)
    service = ToolExecutionService(registry, ToolSchemaValidator())
    await service.execute(ToolExecutionRequest("github__create_issue", {"title": "Bug"}))
    assert client.received_tool_name == "create_issue"


@pytest.mark.anyio
async def test_register_returns_empty_tuple_for_empty_discovery() -> None:
    registrations = await MCPToolRegistrationService().register(ToolRegistry(), FakeMCPClient(()), "github")

    assert registrations == ()


@pytest.mark.anyio
async def test_register_propagates_registry_duplicate_errors() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition("github__create_issue", "Existing tool.", {"type": "object"})
    registry.register(definition, NativeCallableToolExecutor(lambda: None))

    with pytest.raises(ToolRegistryError) as error_info:
        await MCPToolRegistrationService().register(
            registry,
            FakeMCPClient((_descriptor("create_issue"),)),
            "github",
        )

    assert error_info.value.code is ToolRegistryErrorCode.DUPLICATE_TOOL
