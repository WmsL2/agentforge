"""In-memory registry for Tool Platform registrations."""

from app.services.tool.definition.domain import ToolDefinition
from app.services.tool.execution.executor.contract import ToolExecutor
from app.services.tool.registry.domain import (
    ToolRegistration,
    ToolRegistryError,
    ToolRegistryErrorCode,
)


class ToolRegistry:
    """Store and resolve registered tool definitions and their executors."""

    def __init__(self) -> None:
        self._registrations: dict[str, ToolRegistration] = {}

    def register(self, definition: ToolDefinition, executor: ToolExecutor) -> ToolRegistration:
        """Register a definition and executor, rejecting duplicate tool names."""
        if definition.name in self._registrations:
            raise ToolRegistryError(
                ToolRegistryErrorCode.DUPLICATE_TOOL,
                f"Tool '{definition.name}' is already registered.",
            )

        registration = ToolRegistration(definition=definition, executor=executor)
        self._registrations[definition.name] = registration
        return registration

    def resolve(self, tool_name: str) -> ToolRegistration:
        """Resolve a registration by tool name."""
        try:
            return self._registrations[tool_name]
        except KeyError:
            raise ToolRegistryError(
                ToolRegistryErrorCode.TOOL_NOT_FOUND,
                f"Tool '{tool_name}' was not found.",
            ) from None

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return a snapshot of registered definitions in registration order."""
        return tuple(registration.definition for registration in self._registrations.values())
