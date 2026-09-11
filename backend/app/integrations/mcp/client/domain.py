"""Pure domain contracts for MCP clients."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class MCPToolDescriptor:
    """A normalized description of a tool discovered from an MCP server."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot mappings so descriptors cannot be changed by callers."""
        object.__setattr__(self, "input_schema", MappingProxyType(dict(self.input_schema)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class MCPToolCallResult:
    """A normalized result returned by one MCP tool call."""

    output: Any = None
    is_error: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot metadata so callers receive a read-only result mapping."""
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class MCPClientError(RuntimeError):
    """A framework-independent error raised at the MCP client boundary."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)
