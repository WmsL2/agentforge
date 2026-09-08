"""Pure domain contracts for tool definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    """A framework-independent description of a tool and its input schema."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Snapshot mappings so the definition cannot be changed by its caller."""
        object.__setattr__(self, "input_schema", MappingProxyType(dict(self.input_schema)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
