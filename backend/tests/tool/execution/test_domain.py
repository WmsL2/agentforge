"""Tests for framework-independent tool execution contracts."""

from typing import Any

import pytest

from app.services.tool.execution import (
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
)


def test_execution_request_preserves_tool_name_and_arguments() -> None:
    arguments: dict[str, Any] = {"city": "Shanghai"}
    request = ToolExecutionRequest(
        tool_name="weather_lookup",
        arguments=arguments,
        metadata={"source": "workflow"},
    )

    assert request.tool_name == "weather_lookup"
    assert request.arguments == {"city": "Shanghai"}
    assert request.metadata == {"source": "workflow"}


def test_execution_request_arguments_are_a_read_only_shallow_snapshot() -> None:
    arguments: dict[str, Any] = {"city": "Shanghai"}
    request = ToolExecutionRequest(tool_name="weather_lookup", arguments=arguments)

    arguments["city"] = "Beijing"

    assert request.arguments["city"] == "Shanghai"
    with pytest.raises(TypeError):
        request.arguments["city"] = "Shenzhen"  # type: ignore[index]


def test_execution_request_metadata_is_a_read_only_shallow_snapshot() -> None:
    metadata = {"source": "workflow"}
    request = ToolExecutionRequest(tool_name="weather_lookup", metadata=metadata)

    metadata["source"] = "changed"

    assert request.metadata["source"] == "workflow"
    with pytest.raises(TypeError):
        request.metadata["source"] = "runner"  # type: ignore[index]


def test_execution_result_preserves_generic_output_and_read_only_metadata_snapshot() -> None:
    metadata = {"provider": "native"}
    output = {"temperature_c": 24}
    result = ToolExecutionResult(output=output, metadata=metadata)

    metadata["provider"] = "changed"

    assert result.output is output
    assert result.metadata["provider"] == "native"
    with pytest.raises(TypeError):
        result.metadata["provider"] = "other"  # type: ignore[index]


def test_execution_error_preserves_properties_and_message() -> None:
    error = ToolExecutionError("provider_unavailable", "Provider is unavailable.", retryable=True)

    assert error.code == "provider_unavailable"
    assert error.message == "Provider is unavailable."
    assert error.retryable is True
    assert str(error) == "Provider is unavailable."
