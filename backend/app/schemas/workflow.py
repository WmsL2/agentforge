"""HTTP schemas for workflow CRUD."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.services.workflow.definition.model.domain import WorkflowNodeKind
from app.services.workflow.definition.validation.validator import WorkflowValidationCode


class WorkflowNodeSchema(BaseSchema):
    id: str
    kind: WorkflowNodeKind
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdgeSchema(BaseSchema):
    id: str
    source: str
    target: str
    condition: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowGraphSchema(BaseSchema):
    entry_node_id: str
    nodes: list[WorkflowNodeSchema]
    edges: list[WorkflowEdgeSchema]
    schema_version: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    definition: WorkflowGraphSchema


class WorkflowUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    definition: WorkflowGraphSchema | None = None


class WorkflowRead(BaseSchema):
    id: UUID
    user_id: UUID
    name: str
    description: str | None
    definition: WorkflowGraphSchema
    revision: int
    created_at: datetime
    updated_at: datetime | None


class WorkflowList(BaseSchema):
    items: list[WorkflowRead]
    total: int


class WorkflowValidationIssueRead(BaseSchema):
    code: WorkflowValidationCode
    message: str
    node_id: str | None = None
    edge_id: str | None = None


class WorkflowValidationRead(BaseSchema):
    is_valid: bool
    issues: list[WorkflowValidationIssueRead]
