"""Pure domain contracts for agent execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class AgentExecutionRequest:
    """The framework-independent input to one agent execution."""

    instruction: str
    input: Any
    model: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot metadata so runners cannot mutate caller-owned state."""
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class AgentExecutionResult:
    """The framework-independent result of one agent execution."""

    output: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot metadata so callers receive a read-only result mapping."""
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class AgentRuntimeError(RuntimeError):
    """A framework-independent error raised during agent execution."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)
