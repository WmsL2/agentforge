"""Domain values for background workflow execution."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class WorkflowExecutionJob:
    """Describes a workflow run to be executed in the background."""

    run_id: UUID
