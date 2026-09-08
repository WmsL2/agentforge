"""Pure domain contracts for tool execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ToolExecutionRequest:
    """The framework-independent input to one tool invocation."""

    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot mappings so executors cannot mutate caller-owned state."""
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class ToolExecutionResult:
    """The framework-independent result of one tool invocation."""

    output: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot metadata so callers receive a read-only result mapping."""
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class ToolExecutionError(RuntimeError):
    """A framework-independent error raised during tool execution."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)
