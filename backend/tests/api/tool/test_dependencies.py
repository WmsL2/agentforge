"""Production Tool Platform dependency composition tests."""

from types import SimpleNamespace

import pytest

from app.api.deps import get_tool_execution_service, get_tool_registry
from app.composition.tool_platform import open_tool_platform
from app.services.tool import ToolExecutionError, ToolExecutionRequest
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor


def _request_with_registry(registry):
    return SimpleNamespace(state=SimpleNamespace(tool_registry=registry))


@pytest.mark.anyio
async def test_production_registry_contains_current_datetime_native_tool() -> None:
    async with open_tool_platform(()) as shared_registry:
        registry = get_tool_registry(_request_with_registry(shared_registry))

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
    async with open_tool_platform(()) as registry:
        service = get_tool_execution_service(get_tool_registry(_request_with_registry(registry)))

        result = await service.execute(ToolExecutionRequest(tool_name="current_datetime", arguments={}))

        assert set(result.output) == {"date", "time", "datetime"}
        assert all(isinstance(value, str) for value in result.output.values())


@pytest.mark.anyio
async def test_production_service_rejects_unexpected_current_datetime_arguments() -> None:
    async with open_tool_platform(()) as registry:
        service = get_tool_execution_service(get_tool_registry(_request_with_registry(registry)))

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
    async with open_tool_platform(()) as registry:
        service = get_tool_execution_service(get_tool_registry(_request_with_registry(registry)))

        with pytest.raises(ToolExecutionError) as error_info:
            await service.execute(ToolExecutionRequest(tool_name="missing_tool"))

        assert error_info.value.code == "tool_not_found"


def test_tool_registry_dependency_returns_the_lifespan_shared_registry() -> None:
    shared_registry = object()
    request = _request_with_registry(shared_registry)

    assert get_tool_registry(request) is shared_registry
