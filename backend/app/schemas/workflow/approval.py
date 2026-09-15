"""HTTP schemas for workflow approval requests."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.services.workflow.execution.approval import ApprovalRequestStatus


class ApprovalRequestRead(BaseSchema):
    id: UUID
    run_id: UUID
    workflow_revision: int
    node_id: str
    prompt: str
    status: ApprovalRequestStatus
    created_at: datetime
    decided_at: datetime | None
    decided_by: UUID | None
    decision_note: str | None


class ApprovalDecisionRequest(BaseSchema):
    note: str | None = Field(default=None, max_length=2000)
