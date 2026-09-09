"""Tests for the unified ToolExecutionService boundary."""

from typing import Any

import pytest

from app.services.tool import (
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionService,
    ToolRegistry,
)
from app.services.tool.definition.validation import ToolSchemaValidator
from app.services.tool.execution import ToolExecutionService as ExecutionPackageToolExecutionService
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor


class RecordingExecutor:
    """A fake executor that records whether the service invoked it."""

    def __init__(self, output: Any = None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.received_request: ToolExecutionRequest | None = None

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.received_request = request
        if self.error is not None:
            raise self.error
        return ToolExecutionResult(output=self.output)


def _service(definition: ToolDefinition, executor: RecordingExecutor | NativeCallableToolExecutor) -> ToolExecutionService:
    registry = ToolRegistry()
    registry.register(definition, executor)
    return ToolExecutionService(registry, ToolSchemaValidator())


def _add_definition() -> ToolDefinition:
    return ToolDefinition(
        name="add",
        description="Add two integers.",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    )


@pytest.mark.anyio
async def test_service_completes_full_atomic_1_to_6_execution_flow() -> None:
    def add(a: int, b: int) -> int:
        return a + b

    service = _service(_add_definition(), NativeCallableToolExecutor(add))

    result = await service.execute(ToolExecutionRequest(tool_name="add", arguments={"a": 1, "b": 2}))

    assert result.output == 3


@pytest.mark.anyio
async def test_service_normalizes_unknown_tool_registry_error() -> None:
    service = ToolExecutionService(ToolRegistry(), ToolSchemaValidator())

    with pytest.raises(ToolExecutionError) as error_info:
        await service.execute(ToolExecutionRequest(tool_name="missing_tool"))

    error = error_info.value
    assert error.code == "tool_not_found"
    assert error.retryable is False


@pytest.mark.anyio
async def test_service_reports_all_invalid_argument_issues_without_executing() -> None:
    executor = RecordingExecutor()
    service = _service(_add_definition(), executor)

    with pytest.raises(ToolExecutionError) as error_info:
        await service.execute(ToolExecutionRequest(tool_name="add", arguments={"a": "one"}))

    error = error_info.value
    assert error.code == "invalid_arguments"
    assert "'b' is a required property" in error.message
    assert "a: 'one' is not of type 'integer'" in error.message
    assert executor.received_request is None


@pytest.mark.anyio
async def test_service_rejects_invalid_input_schema_without_executing() -> None:
    definition = ToolDefinition(
        name="broken",
        description="Broken schema.",
        input_schema={"type": "not-a-real-json-schema-type"},
    )
    executor = RecordingExecutor()
    service = _service(definition, executor)

    with pytest.raises(ToolExecutionError) as error_info:
        await service.execute(ToolExecutionRequest(tool_name="broken"))

    assert error_info.value.code == "invalid_input_schema"
    assert executor.received_request is None


@pytest.mark.anyio
async def test_service_normalizes_generic_executor_exception() -> None:
    executor = RecordingExecutor(error=ValueError("boom"))
    service = _service(_add_definition(), executor)

    with pytest.raises(ToolExecutionError) as error_info:
        await service.execute(ToolExecutionRequest(tool_name="add", arguments={"a": 1, "b": 2}))

    error = error_info.value
    assert error.code == "tool_execution_failed"
    assert error.message == "boom"
    assert error.retryable is False


@pytest.mark.anyio
async def test_service_uses_exception_type_when_executor_message_is_empty() -> None:
    executor = RecordingExecutor(error=RuntimeError())
    service = _service(_add_definition(), executor)

    with pytest.raises(ToolExecutionError) as error_info:
        await service.execute(ToolExecutionRequest(tool_name="add", arguments={"a": 1, "b": 2}))

    assert error_info.value.message == "RuntimeError"


@pytest.mark.anyio
async def test_service_preserves_executor_tool_execution_error_identity() -> None:
    original_error = ToolExecutionError(
        code="upstream_unavailable",
        message="provider unavailable",
        retryable=True,
    )
    service = _service(_add_definition(), RecordingExecutor(error=original_error))

    with pytest.raises(ToolExecutionError) as error_info:
        await service.execute(ToolExecutionRequest(tool_name="add", arguments={"a": 1, "b": 2}))

    assert error_info.value is original_error


@pytest.mark.anyio
async def test_service_passes_the_original_request_to_executor() -> None:
    executor = RecordingExecutor(output=3)
    service = _service(_add_definition(), executor)
    request = ToolExecutionRequest(tool_name="add", arguments={"a": 1, "b": 2})

    result = await service.execute(request)

    assert result.output == 3
    assert executor.received_request is request


def test_service_is_exported_from_execution_and_root_packages() -> None:
    assert ExecutionPackageToolExecutionService is ToolExecutionService
