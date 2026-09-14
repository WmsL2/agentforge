from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID


class WorkflowRunStatus(str, Enum):  # noqa: UP042
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WorkflowRunError:
    code: str
    message: str
    node_id: str | None = None


class WorkflowRunTransitionError(ValueError):
    def __init__(self, current: WorkflowRunStatus, attempted: WorkflowRunStatus):
        self.current = current
        self.attempted = attempted
        super().__init__(f"Cannot transition from {current.value} to {attempted.value}")


@dataclass
class WorkflowRun:
    id: UUID
    workflow_id: UUID
    workflow_revision: int
    status: WorkflowRunStatus = WorkflowRunStatus.PENDING
    input: dict[str, Any] = field(default_factory=dict)
    node_outputs: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: WorkflowRunError | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def _go(self, target: WorkflowRunStatus):
        if (self.status, target) not in {
            (WorkflowRunStatus.PENDING, WorkflowRunStatus.RUNNING),
            (WorkflowRunStatus.RUNNING, WorkflowRunStatus.PAUSED),
            (WorkflowRunStatus.PAUSED, WorkflowRunStatus.RUNNING),
            (WorkflowRunStatus.RUNNING, WorkflowRunStatus.COMPLETED),
            (WorkflowRunStatus.RUNNING, WorkflowRunStatus.FAILED),
            (WorkflowRunStatus.PAUSED, WorkflowRunStatus.CANCELLED),
        }:
            raise WorkflowRunTransitionError(self.status, target)
        self.status = target

    def start(self, at: datetime | None = None):
        if self.status is not WorkflowRunStatus.PENDING:
            raise WorkflowRunTransitionError(self.status, WorkflowRunStatus.RUNNING)
        self._go(WorkflowRunStatus.RUNNING)
        self.started_at = at or datetime.now(UTC)

    def pause(self):
        self._go(WorkflowRunStatus.PAUSED)

    def resume(self):
        if self.status is not WorkflowRunStatus.PAUSED:
            raise WorkflowRunTransitionError(self.status, WorkflowRunStatus.RUNNING)
        self._go(WorkflowRunStatus.RUNNING)

    def complete(self, output: dict[str, Any], at: datetime | None = None):
        self._go(WorkflowRunStatus.COMPLETED)
        self.output = output
        self.error = None
        self.finished_at = at or datetime.now(UTC)

    def fail(self, error: WorkflowRunError, at: datetime | None = None):
        self._go(WorkflowRunStatus.FAILED)
        self.error = error
        self.output = None
        self.finished_at = at or datetime.now(UTC)

    def cancel(self, at: datetime | None = None):
        self._go(WorkflowRunStatus.CANCELLED)
        self.output = None
        self.error = None
        self.finished_at = at or datetime.now(UTC)
