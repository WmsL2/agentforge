"""Domain values for background workflow execution."""

from dataclasses import dataclass
from datetime import datetime
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
