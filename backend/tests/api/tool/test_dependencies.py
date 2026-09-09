"""Production Tool Platform dependency composition tests."""

import pytest

from app.api.deps import get_tool_execution_service, get_tool_registry
from app.services.tool import ToolExecutionError, ToolExecutionRequest
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor


def test_production_registry_contains_current_datetime_native_tool() -> None:
    registry = get_tool_registry()

    registration = registry.resolve("current_datetime")

    assert registration.definition.name == "current_datetime"
    assert registration.definition.input_schema == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert isinstance(registration.executor, NativeCallableToolExecutor)


@pytest.mark.anyio
async def test_production_service_executes_current_datetime_through_full_chain() -> None:
    service = get_tool_execution_service(get_tool_registry())

    result = await service.execute(ToolExecutionRequest(tool_name="current_datetime", arguments={}))

    assert set(result.output) == {"date", "time", "datetime"}
    assert all(isinstance(value, str) for value in result.output.values())


@pytest.mark.anyio
async def test_production_service_rejects_unexpected_current_datetime_arguments() -> None:
    service = get_tool_execution_service(get_tool_registry())

    with pytest.raises(ToolExecutionError) as error_info:
        await service.execute(
            ToolExecutionRequest(
                tool_name="current_datetime",
                arguments={"timezone": "Asia/Tokyo"},
            )
        )

    assert error_info.value.code == "invalid_arguments"


@pytest.mark.anyio
async def test_production_service_normalizes_unknown_tool() -> None:
    service = get_tool_execution_service(get_tool_registry())

    with pytest.raises(ToolExecutionError) as error_info:
        await service.execute(ToolExecutionRequest(tool_name="missing_tool"))

    assert error_info.value.code == "tool_not_found"


def test_tool_registry_factory_creates_isolated_registries() -> None:
    registry_a = get_tool_registry()
    registry_b = get_tool_registry()

    assert registry_a is not registry_b
