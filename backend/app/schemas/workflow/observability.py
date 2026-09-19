"""HTTP read models for persisted workflow observability history."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, computed_field

from app.schemas.base import BaseSchema
from app.services.workflow.definition import WorkflowNodeKind
from app.services.workflow.execution.observability import RunStepStatus, TraceEventKind


class WorkflowRunStepErrorRead(BaseSchema):
    code: str
    message: str


class WorkflowRunStepRead(BaseSchema):
    id: UUID
    run_id: UUID
    sequence: int
    node_id: str
    node_kind: WorkflowNodeKind
    status: RunStepStatus
    input: dict[str, Any]
    output: Any | None
    error: WorkflowRunStepErrorRead | None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    started_at: datetime
    finished_at: datetime | None

    @computed_field
    @property
    def duration_ms(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds() * 1000


class WorkflowTraceEventRead(BaseSchema):
    id: UUID
    run_id: UUID
    step_id: UUID | None
    kind: TraceEventKind
    payload: dict[str, Any]
    created_at: datetime
