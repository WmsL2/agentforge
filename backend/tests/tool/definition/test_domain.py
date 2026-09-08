"""Tests for framework-independent tool definition contracts."""

from typing import Any

import pytest

from app.services.tool.definition import ToolDefinition


def test_tool_definition_preserves_fields() -> None:
    schema: dict[str, Any] = {"type": "object", "properties": {"city": {"type": "string"}}}
    definition = ToolDefinition(
        name="weather_lookup",
        description="Look up the weather for a city.",
        input_schema=schema,
        metadata={"provider": "native"},
    )

    assert definition.name == "weather_lookup"
    assert definition.description == "Look up the weather for a city."
    assert definition.input_schema == schema
    assert definition.metadata == {"provider": "native"}


def test_tool_definition_input_schema_is_a_read_only_shallow_snapshot() -> None:
    schema: dict[str, Any] = {"type": "object"}
    definition = ToolDefinition(name="lookup", description="Look up data.", input_schema=schema)

    schema["type"] = "array"

    assert definition.input_schema["type"] == "object"
    with pytest.raises(TypeError):
        definition.input_schema["type"] = "string"  # type: ignore[index]


def test_tool_definition_metadata_is_a_read_only_shallow_snapshot() -> None:
    metadata = {"provider": "native"}
    definition = ToolDefinition(
        name="lookup",
        description="Look up data.",
        input_schema={},
        metadata=metadata,
    )

    metadata["provider"] = "changed"

    assert definition.metadata["provider"] == "native"
    with pytest.raises(TypeError):
        definition.metadata["provider"] = "other"  # type: ignore[index]
