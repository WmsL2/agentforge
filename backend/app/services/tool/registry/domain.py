"""Pure domain contracts for tool registrations."""

from dataclasses import dataclass
from enum import Enum

from app.services.tool.definition.domain import ToolDefinition
from app.services.tool.execution.executor.contract import ToolExecutor


@dataclass(frozen=True)
class ToolRegistration:
    """A tool definition and the executor responsible for invoking it."""

    definition: ToolDefinition
    executor: ToolExecutor


class ToolRegistryErrorCode(str, Enum):  # noqa: UP042
    """Stable machine-readable errors produced by a ToolRegistry."""

    DUPLICATE_TOOL = "duplicate_tool"
    TOOL_NOT_FOUND = "tool_not_found"


class ToolRegistryError(RuntimeError):
    """A deterministic registration or lookup failure."""

    def __init__(self, code: ToolRegistryErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
