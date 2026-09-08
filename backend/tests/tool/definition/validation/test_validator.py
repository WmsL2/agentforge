"""Tests for tool JSON Schema validation."""

from app.services.tool import ToolDefinition, ToolExecutionRequest
from app.services.tool.definition.validation import (
    ToolSchemaValidationCode,
    ToolSchemaValidator,
)


def _definition(schema: dict[object, object]) -> ToolDefinition:
    return ToolDefinition(name="weather_lookup", description="Look up the weather.", input_schema=schema)


def test_validate_schema_accepts_a_valid_draft_2020_12_object_schema() -> None:
    result = ToolSchemaValidator().validate_schema(
        _definition(
            {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            }
        )
    )

    assert result.is_valid is True
    assert result.issues == ()


def test_validate_schema_returns_invalid_input_schema_instead_of_raising() -> None:
    result = ToolSchemaValidator().validate_schema(
        _definition({"type": "not-a-real-json-schema-type"})
    )

    assert result.is_valid is False
    assert len(result.issues) == 1
    assert result.issues[0].code is ToolSchemaValidationCode.INVALID_INPUT_SCHEMA


def test_validate_arguments_accepts_valid_arguments() -> None:
    definition = _definition(
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        }
    )

    result = ToolSchemaValidator().validate_arguments(definition, {"city": "Shanghai"})

    assert result.is_valid is True
    assert result.issues == ()


def test_validate_arguments_reports_missing_required_property() -> None:
    definition = _definition(
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        }
    )

    result = ToolSchemaValidator().validate_arguments(definition, {})

    assert result.is_valid is False
    assert result.issues[0].code is ToolSchemaValidationCode.INVALID_ARGUMENTS
    assert "'city' is a required property" in result.issues[0].message


def test_validate_arguments_reports_wrong_property_type_at_its_path() -> None:
    definition = _definition(
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
        }
    )

    result = ToolSchemaValidator().validate_arguments(definition, {"city": 123})

    assert result.is_valid is False
    assert result.issues[0].code is ToolSchemaValidationCode.INVALID_ARGUMENTS
    assert result.issues[0].path == ("city",)


def test_validate_arguments_rejects_unknown_properties() -> None:
    definition = _definition(
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "additionalProperties": False,
        }
    )

    result = ToolSchemaValidator().validate_arguments(definition, {"city": "Shanghai", "unit": "c"})

    assert result.is_valid is False
    assert result.issues[0].code is ToolSchemaValidationCode.INVALID_ARGUMENTS
    assert "'unit' was unexpected" in result.issues[0].message


def test_validate_arguments_collects_multiple_errors_in_deterministic_order() -> None:
    definition = _definition(
        {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "days": {"type": "integer"},
            },
            "additionalProperties": False,
        }
    )
    arguments = {"city": 123, "days": "three", "unit": "c"}

    validator = ToolSchemaValidator()
    first_result = validator.validate_arguments(definition, arguments)
    second_result = validator.validate_arguments(definition, arguments)

    assert len(first_result.issues) == 3
    assert all(issue.code is ToolSchemaValidationCode.INVALID_ARGUMENTS for issue in first_result.issues)
    assert [issue.path for issue in first_result.issues] == [(), ("city",), ("days",)]
    assert first_result.issues == second_result.issues


def test_validate_arguments_accepts_atomic_1_mapping_proxy_contracts() -> None:
    definition = _definition(
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        }
    )
    request = ToolExecutionRequest(tool_name="weather_lookup", arguments={"city": "Shanghai"})

    result = ToolSchemaValidator().validate_arguments(definition, request.arguments)

    assert result.is_valid is True


def test_validate_arguments_returns_invalid_input_schema_without_validating_arguments() -> None:
    definition = _definition({"type": "not-a-real-json-schema-type"})

    result = ToolSchemaValidator().validate_arguments(definition, {"city": 123})

    assert result.is_valid is False
    assert len(result.issues) == 1
    assert result.issues[0].code is ToolSchemaValidationCode.INVALID_INPUT_SCHEMA
