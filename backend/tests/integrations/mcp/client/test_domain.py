"""Tests for framework-independent MCP client domain contracts."""

from typing import Any

import pytest

from app.integrations.mcp import MCPClientError, MCPToolCallResult, MCPToolDescriptor


def test_tool_descriptor_preserves_its_fields() -> None:
    descriptor = MCPToolDescriptor(
        name="create_issue",
        description="Create an issue.",
        input_schema={"type": "object"},
        metadata={"server": "github"},
    )

    assert descriptor.name == "create_issue"
    assert descriptor.description == "Create an issue."
    assert descriptor.input_schema == {"type": "object"}
    assert descriptor.metadata == {"server": "github"}


def test_tool_descriptor_input_schema_is_a_read_only_shallow_snapshot() -> None:
    input_schema: dict[str, Any] = {"type": "object"}
    descriptor = MCPToolDescriptor(
        name="create_issue",
        description="Create an issue.",
        input_schema=input_schema,
    )

    input_schema["type"] = "array"

    assert descriptor.input_schema["type"] == "object"
    with pytest.raises(TypeError):
        descriptor.input_schema["type"] = "string"  # type: ignore[index]


def test_tool_descriptor_metadata_is_a_read_only_shallow_snapshot() -> None:
    metadata = {"server": "github"}
    descriptor = MCPToolDescriptor(
        name="create_issue",
        description="Create an issue.",
        input_schema={},
        metadata=metadata,
    )

    metadata["server"] = "gitlab"

    assert descriptor.metadata["server"] == "github"
    with pytest.raises(TypeError):
        descriptor.metadata["server"] = "linear"  # type: ignore[index]


def test_tool_call_result_preserves_fields_and_metadata_snapshot() -> None:
    metadata = {"request_id": "request-1"}
    output = {"issue": 42}
    result = MCPToolCallResult(output=output, is_error=True, metadata=metadata)

    metadata["request_id"] = "request-2"

    assert result.output is output
    assert result.is_error is True
    assert result.metadata["request_id"] == "request-1"
    with pytest.raises(TypeError):
        result.metadata["request_id"] = "request-3"  # type: ignore[index]


def test_client_error_preserves_properties_and_message() -> None:
    error = MCPClientError("transport_failure", "Transport failed.", retryable=True)

    assert error.code == "transport_failure"
    assert error.message == "Transport failed."
    assert error.retryable is True
    assert str(error) == "Transport failed."
