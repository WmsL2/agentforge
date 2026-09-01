"""Pure contracts between workflow scheduling and node execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID

from app.services.workflow.domain import WorkflowNode


@dataclass(frozen=True)
class NodeExecutionContext:
    """The read-only data available to one node execution."""

    run_id: UUID
    workflow_input: Mapping[str, Any]
    upstream_outputs: Mapping[str, Any]
    node_outputs: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Snapshot mappings so executors cannot mutate engine-owned state."""
        object.__setattr__(self, "workflow_input", MappingProxyType(dict(self.workflow_input)))
        object.__setattr__(self, "upstream_outputs", MappingProxyType(dict(self.upstream_outputs)))
        object.__setattr__(self, "node_outputs", MappingProxyType(dict(self.node_outputs)))


@dataclass
class NodeExecutionResult:
    """The result produced by a node executor."""

    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class NodeExecutor(Protocol):
    """Execute one workflow node using an asynchronous contract."""

    async def execute(
        self,
        node: WorkflowNode,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        """Execute ``node`` and return only its local result."""
