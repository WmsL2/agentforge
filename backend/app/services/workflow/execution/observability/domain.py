"""Pure domain contracts for workflow execution observability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any
from uuid import UUID

from app.services.workflow.definition.model.domain import WorkflowNodeKind


class RunStepStatus(str, Enum):  # noqa: UP042
    """The lifecycle states of one actual node execution attempt."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class RunStepError:
    """The structured error outcome of one run step."""

    code: str
    message: str


class RunStepTransitionError(ValueError):
    """Raised when an execution attempt receives an invalid lifecycle transition."""

    def __init__(self, current: RunStepStatus, attempted: RunStepStatus):
        self.current = current
        self.attempted = attempted
        super().__init__(f"Cannot transition from {current.value} to {attempted.value}")


@dataclass
class RunStep:
    """A structured summary of one real ``NodeExecutor.execute()`` attempt."""

    id: UUID
    run_id: UUID
    sequence: int
    node_id: str
    node_kind: WorkflowNodeKind
    input: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    status: RunStepStatus = RunStepStatus.RUNNING
    output: Any | None = None
    error: RunStepError | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("Run step sequence must be at least 1.")
        if not self.node_id:
            raise ValueError("Run step node ID must not be empty.")

        self.input = MappingProxyType(dict(self.input))
        self.metadata = MappingProxyType(dict(self.metadata))

    def _go(self, target: RunStepStatus) -> None:
        if self.status is not RunStepStatus.RUNNING:
            raise RunStepTransitionError(self.status, target)
        self.status = target

    def complete(
        self,
        output: Any,
        metadata: Mapping[str, Any],
        at: datetime | None = None,
    ) -> None:
        """Record successful completion of this execution attempt."""
        self._go(RunStepStatus.COMPLETED)
        self.output = output
        self.error = None
        self.metadata = MappingProxyType(dict(metadata))
        self.finished_at = at or datetime.now(UTC)

    def fail(
        self,
        error: RunStepError,
        metadata: Mapping[str, Any],
        at: datetime | None = None,
    ) -> None:
        """Record failed completion of this execution attempt."""
        self._go(RunStepStatus.FAILED)
        self.error = error
        self.output = None
        self.metadata = MappingProxyType(dict(metadata))
        self.finished_at = at or datetime.now(UTC)

    def interrupt(
        self,
        output: Any | None,
        metadata: Mapping[str, Any],
        at: datetime | None = None,
    ) -> None:
        """Record an interrupted execution attempt without an error outcome."""
        self._go(RunStepStatus.INTERRUPTED)
        self.output = output
        self.error = None
        self.metadata = MappingProxyType(dict(metadata))
        self.finished_at = at or datetime.now(UTC)


class TraceEventKind(str, Enum):  # noqa: UP042
    """The supported immutable execution-history event kinds."""

    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_INTERRUPTED = "node_interrupted"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_APPROVED = "approval_approved"
    APPROVAL_REJECTED = "approval_rejected"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"


@dataclass(frozen=True)
class TraceEvent:
    """An append-only, framework-independent execution-history record."""

    id: UUID
    run_id: UUID
    step_id: UUID | None
    kind: TraceEventKind
    payload: Mapping[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
