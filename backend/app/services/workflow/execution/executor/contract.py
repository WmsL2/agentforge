"""Pure contracts between workflow scheduling and node execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID

from app.services.workflow.definition.model.domain import WorkflowNode


class NodeExecutionOutcome(str, Enum):  # noqa: UP042
    """The scheduling outcome returned by a node executor."""

    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class NodeExecutionInterrupt:
    """Immutable data explaining why a node interrupted execution."""

    type: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.type, str) or not self.type.strip():
            raise ValueError("Node execution interrupt type must be a non-blank string.")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


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
    outcome: NodeExecutionOutcome = NodeExecutionOutcome.COMPLETED
    interrupt: NodeExecutionInterrupt | None = None

    def __post_init__(self) -> None:
        if self.outcome is NodeExecutionOutcome.COMPLETED and self.interrupt is not None:
            raise ValueError("Completed node execution results cannot include an interrupt.")
        if self.outcome is NodeExecutionOutcome.INTERRUPTED and (
            self.interrupt is None or self.output is not None
        ):
            raise ValueError("Interrupted node execution results require an interrupt and no output.")


class NodeExecutor(Protocol):
    """Execute one workflow node using an asynchronous contract."""

    async def execute(
        self,
        node: WorkflowNode,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        """Execute ``node`` and return only its local result."""
