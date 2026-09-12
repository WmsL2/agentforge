"""Tests for ToolRegistry."""

import pytest

from app.services.tool import (
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolRegistry,
    ToolRegistryError,
    ToolRegistryErrorCode,
)
from app.services.tool.registry import ToolRegistry as RegistryPackageToolRegistry


class FakeToolExecutor:
    """A structural executor used only to register tools in tests."""

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return ToolExecutionResult(output=request.tool_name)


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=f"{name} description", input_schema={"type": "object"})


def test_register_and_resolve_preserve_original_definition_and_executor() -> None:
    registry = ToolRegistry()
    definition = _definition("weather_lookup")
    executor = FakeToolExecutor()

    registration = registry.register(definition, executor)
    resolved = registry.resolve(definition.name)

    assert registration is resolved
    assert registration.definition is definition
    assert registration.executor is executor


def test_duplicate_registration_does_not_replace_original_registration() -> None:
    registry = ToolRegistry()
    first_definition = _definition("weather_lookup")
    first_executor = FakeToolExecutor()
    registry.register(first_definition, first_executor)

    with pytest.raises(ToolRegistryError) as error_info:
        registry.register(_definition("weather_lookup"), FakeToolExecutor())

    assert error_info.value.code is ToolRegistryErrorCode.DUPLICATE_TOOL
    resolved = registry.resolve("weather_lookup")
    assert resolved.definition is first_definition
    assert resolved.executor is first_executor


def test_resolve_unknown_tool_returns_stable_error() -> None:
    registry = ToolRegistry()

    with pytest.raises(ToolRegistryError) as error_info:
        registry.resolve("missing_tool")

    error = error_info.value
    assert error.code is ToolRegistryErrorCode.TOOL_NOT_FOUND
    assert str(error) == error.message


def test_different_tool_names_register_and_resolve_independently() -> None:
    registry = ToolRegistry()
    weather_registration = registry.register(_definition("weather_lookup"), FakeToolExecutor())
    time_registration = registry.register(_definition("time_lookup"), FakeToolExecutor())

    assert registry.resolve("weather_lookup") is weather_registration
    assert registry.resolve("time_lookup") is time_registration


def test_definitions_returns_an_empty_tuple_for_an_empty_registry() -> None:
    definitions = ToolRegistry().definitions()

    assert definitions == ()
    assert isinstance(definitions, tuple)


def test_definitions_returns_registered_definitions_in_registration_order() -> None:
    registry = ToolRegistry()
    alpha = _definition("alpha")
    beta = _definition("beta")
    gamma = _definition("gamma")
    executor = FakeToolExecutor()
    registry.register(alpha, executor)
    registry.register(beta, executor)
    registry.register(gamma, executor)

    definitions = registry.definitions()

    assert definitions == (alpha, beta, gamma)
    assert all(isinstance(definition, ToolDefinition) for definition in definitions)


def test_definitions_preserves_original_definition_identity() -> None:
    registry = ToolRegistry()
    definition = _definition("weather_lookup")
    registry.register(definition, FakeToolExecutor())

    definitions = registry.definitions()

    assert definitions[0] is definition


def test_definitions_returns_a_snapshot_that_does_not_change_after_registration() -> None:
    registry = ToolRegistry()
    first_definition = _definition("first")
    second_definition = _definition("second")
    registry.register(first_definition, FakeToolExecutor())

    first_snapshot = registry.definitions()
    registry.register(second_definition, FakeToolExecutor())
    second_snapshot = registry.definitions()

    assert first_snapshot == (first_definition,)
    assert second_snapshot == (first_definition, second_definition)
    assert first_snapshot is not second_snapshot


def test_registry_is_exported_from_registry_and_root_packages() -> None:
    assert RegistryPackageToolRegistry is ToolRegistry
