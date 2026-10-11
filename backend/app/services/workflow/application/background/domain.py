"""Domain values for background workflow execution."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True)
class WorkflowExecutionJob:
    """Describes a workflow run to be executed in the background."""

    run_id: UUID


@dataclass(frozen=True)
class WorkflowExecutionLease:
    """Database-issued credentials for one generation of workflow execution."""

    run_id: UUID
    claim_token: UUID
    generation: int
    expires_at: datetime


class WorkflowExecutionLeaseLostError(RuntimeError):
    """The worker no longer owns a valid database execution lease."""


class BackgroundRunStateError(ValueError):
    """Persisted run/checkpoint state cannot safely be executed."""


class WorkflowCheckpointSequenceError(BackgroundRunStateError):
    """The proposed checkpoint does not append to current committed state."""


class BackgroundRunExecutionStatus(StrEnum):
    """Outcomes of one background execution attempt."""

    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"
    NOT_CLAIMED = "not_claimed"
    LEASE_LOST = "lease_lost"


@dataclass(frozen=True)
class BackgroundRunExecutionResult:
    """An explicit execution outcome, including best-effort release information."""

    run_id: UUID
    status: BackgroundRunExecutionStatus
    lease_released: bool = False
    release_error: str | None = None
