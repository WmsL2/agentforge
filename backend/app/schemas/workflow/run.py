"""HTTP schemas for workflow-run execution history."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.workflow.definition import WorkflowGraphSchema
from app.services.workflow.execution.run import WorkflowRunStatus


class WorkflowRunCreate(BaseSchema):
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunErrorRead(BaseSchema):
    code: str
    message: str
    node_id: str | None = None


class WorkflowRunRead(BaseSchema):
    id: UUID
    workflow_id: UUID
    workflow_revision: int
    definition_snapshot: WorkflowGraphSchema
    status: WorkflowRunStatus
    input: dict[str, Any]
    node_outputs: dict[str, Any]
    output: dict[str, Any] | None
    error: WorkflowRunErrorRead | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime | None


class WorkflowRunListItem(BaseSchema):
    id: UUID
    workflow_id: UUID
    workflow_revision: int
    status: WorkflowRunStatus
    error: WorkflowRunErrorRead | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime | None


class WorkflowRunList(BaseSchema):
    items: list[WorkflowRunListItem]
    total: int
