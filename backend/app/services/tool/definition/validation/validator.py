"""Draft 2020-12 JSON Schema validation for tool contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from app.services.tool.definition.domain import ToolDefinition
from app.services.tool.definition.validation.domain import (
    ToolSchemaValidationCode,
    ToolSchemaValidationIssue,
    ToolSchemaValidationResult,
)


class ToolSchemaValidator:
    """A stateless validator for Tool Platform JSON Schema contracts."""

    def validate_schema(self, definition: ToolDefinition) -> ToolSchemaValidationResult:
        """Validate a tool input schema against JSON Schema Draft 2020-12."""
        schema = dict(definition.input_schema)

        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            return ToolSchemaValidationResult(
                (
                    ToolSchemaValidationIssue(
                        code=ToolSchemaValidationCode.INVALID_INPUT_SCHEMA,
                        message=error.message,
                        path=tuple(error.path),
                    ),
                )
            )

        return ToolSchemaValidationResult(())

    def validate_arguments(
        self,
        definition: ToolDefinition,
        arguments: Mapping[str, Any],
    ) -> ToolSchemaValidationResult:
        """Validate one tool invocation's arguments against its input schema."""
        schema_result = self.validate_schema(definition)
        if not schema_result.is_valid:
            return schema_result

        schema = dict(definition.input_schema)
        instance = dict(arguments)
        errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=self._error_sort_key)
        issues = tuple(
            ToolSchemaValidationIssue(
                code=ToolSchemaValidationCode.INVALID_ARGUMENTS,
                message=error.message,
                path=tuple(error.path),
            )
            for error in errors
        )
        return ToolSchemaValidationResult(issues)

    @staticmethod
    def _error_sort_key(error: ValidationError) -> tuple[tuple[str, ...], tuple[str, ...], str]:
        """Build a deterministic sort key while retaining native path components."""
        return (
            tuple(str(component) for component in error.path),
            tuple(str(component) for component in error.schema_path),
            error.message,
        )
