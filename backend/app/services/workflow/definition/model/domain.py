"""Pure Python contracts for AgentForge workflow definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID


class WorkflowNodeKind(str, Enum):  # noqa: UP042
    """The supported workflow node kinds."""

    START = "start"
    VALUE = "value"
    AGENT = "agent"
    END = "end"


@dataclass
class WorkflowNode:
    """A node declared in a workflow definition."""

    id: str
    kind: WorkflowNodeKind
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowEdge:
    """A directed connection declared in a workflow definition."""

    id: str
    source: str
    target: str
    condition: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowDefinition:
    """An ordered workflow representation without graph validation."""

    id: UUID
    name: str
    entry_node_id: str
    description: str | None = None
    nodes: tuple[WorkflowNode, ...] = field(default_factory=tuple)
    edges: tuple[WorkflowEdge, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    revision: int = 1
