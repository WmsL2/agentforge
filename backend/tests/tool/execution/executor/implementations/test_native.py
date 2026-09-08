"""Tests for NativeCallableToolExecutor."""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.services.tool import ToolDefinition, ToolExecutionRequest, ToolRegistry
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor


@pytest.mark.anyio
async def test_sync_callable_receives_mapping_proxy_arguments() -> None:
    def add(a: int, b: int) -> int:
        return a + b

    executor = NativeCallableToolExecutor(add)
    request = ToolExecutionRequest(tool_name="add", arguments={"a": 1, "b": 2})

    result = await executor.execute(request)

    assert result.output == 3


@pytest.mark.anyio
async def test_async_callable_is_awaited() -> None:
    async def add(a: int, b: int) -> int:
        return a + b

    result = await NativeCallableToolExecutor(add).execute(
        ToolExecutionRequest(tool_name="add", arguments={"a": 1, "b": 2})
    )

    assert result.output == 3


@pytest.mark.anyio
async def test_sync_callable_returning_awaitable_is_awaited() -> None:
    async def resolve_value() -> str:
        return "resolved"

    def returns_awaitable() -> Awaitable[str]:
        return resolve_value()

    result = await NativeCallableToolExecutor(returns_awaitable).execute(
        ToolExecutionRequest(tool_name="resolve_value")
    )

    assert result.output == "resolved"


@pytest.mark.anyio
async def test_zero_argument_callable_executes() -> None:
    def current_value() -> str:
        return "current"

    result = await NativeCallableToolExecutor(current_value).execute(
        ToolExecutionRequest(tool_name="current_value")
    )

    assert result.output == "current"


@pytest.mark.anyio
async def test_metadata_and_tool_name_are_not_passed_to_callable() -> None:
    received: dict[str, Any] = {}

    def echo(value: str) -> str:
        received["value"] = value
        return value

    result = await NativeCallableToolExecutor(echo).execute(
        ToolExecutionRequest(
            tool_name="echo",
            arguments={"value": "hello"},
            metadata={"source": "test"},
        )
    )

    assert received == {"value": "hello"}
    assert result.output == "hello"


@pytest.mark.anyio
async def test_structured_output_is_preserved() -> None:
    output = {"temperature": 24, "conditions": ["clear"]}

    def weather() -> dict[str, object]:
        return output

    result = await NativeCallableToolExecutor(weather).execute(
        ToolExecutionRequest(tool_name="weather")
    )

    assert result.output is output


@pytest.mark.anyio
async def test_callable_exceptions_propagate_unchanged() -> None:
    def broken() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await NativeCallableToolExecutor(broken).execute(ToolExecutionRequest(tool_name="broken"))


@pytest.mark.anyio
async def test_registry_registration_resolves_and_executes_native_callable() -> None:
    def add(a: int, b: int) -> int:
        return a + b

    definition = ToolDefinition(
        name="add",
        description="Add two numbers.",
        input_schema={"type": "object"},
    )
    executor = NativeCallableToolExecutor(add)
    registry = ToolRegistry()
    registry.register(definition, executor)

    result = await registry.resolve("add").executor.execute(
        ToolExecutionRequest(tool_name="add", arguments={"a": 1, "b": 2})
    )

    assert result.output == 3


def test_native_callable_executor_is_publicly_exported() -> None:
    assert NativeCallableToolExecutor.__name__ == "NativeCallableToolExecutor"


def test_non_callable_constructor_argument_is_rejected() -> None:
    non_callable: Callable[..., Any] = 42  # type: ignore[assignment]

    with pytest.raises(TypeError, match="callable_"):
        NativeCallableToolExecutor(non_callable)
