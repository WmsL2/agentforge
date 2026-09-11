"""Tests for MCP tool discovery domain contracts."""

from dataclasses import FrozenInstanceError

import pytest

from app.integrations.mcp.discovery import MCPDiscoveredTool, MCPToolDiscoveryError
from app.services.tool import ToolDefinition


def test_discovered_tool_preserves_remote_name_and_definition() -> None:
    definition = ToolDefinition(
        name="github__create_issue",
        description="Create an issue.",
        input_schema={"type": "object"},
    )
    discovered = MCPDiscoveredTool(remote_name="create_issue", definition=definition)

    assert discovered.remote_name == "create_issue"
    assert discovered.definition is definition
    with pytest.raises(FrozenInstanceError):
        discovered.remote_name = "search_issues"  # type: ignore[misc]


def test_discovery_error_preserves_properties_and_message() -> None:
    error = MCPToolDiscoveryError(
        "invalid_tool_schema",
        "Schema is invalid.",
        tool_name="create_issue",
    )

    assert error.code == "invalid_tool_schema"
    assert error.message == "Schema is invalid."
    assert error.tool_name == "create_issue"
    assert str(error) == "Schema is invalid."
