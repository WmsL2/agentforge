"""Ownership-safe approval query and decision orchestration."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundError
from app.db.models.workflow.approval.model import ApprovalRequest as DBApprovalRequest
from app.db.models.workflow.run.model import WorkflowRun as DBWorkflowRun
from app.repositories.workflow.approval import repository as approval_repo
from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.application.definition.service import WorkflowService
from app.services.workflow.execution.approval import (
    ApprovalRequest,
    ApprovalRequestTransitionError,
    deserialize_approval_request,
)
from app.services.workflow.execution.run import WorkflowRunStatus


class WorkflowApprovalConflictError(AppException):
    """Raised when a decision cannot be applied to an approval request."""

    status_code = 409
    code = "APPROVAL_CONFLICT"
    message = "Approval request cannot be decided."


class WorkflowApprovalService:
    """Coordinate approval persistence without resuming or cancelling workflows."""

    def __init__(self, db: AsyncSession, workflow_service: WorkflowService):
        self.db = db
        self.workflow_service = workflow_service

    async def get_pending_approval(
        self, workflow_id: UUID, run_id: UUID, user_id: UUID
    ) -> DBApprovalRequest:
        await self._get_owned_run(workflow_id, run_id, user_id)
        approval = await approval_repo.get_pending_approval_by_run(self.db, run_id)
        if approval is None:
            raise NotFoundError(message="Pending approval request not found")
        return approval

    async def approve(
        self,
        workflow_id: UUID,
        run_id: UUID,
        approval_id: UUID,
        user_id: UUID,
        *,
        note: str | None = None,
    ) -> DBApprovalRequest:
        return await self._decide(
            workflow_id, run_id, approval_id, user_id, approved=True, note=note
        )

    async def reject(
        self,
        workflow_id: UUID,
        run_id: UUID,
        approval_id: UUID,
        user_id: UUID,
        *,
        note: str | None = None,
    ) -> DBApprovalRequest:
        return await self._decide(
            workflow_id, run_id, approval_id, user_id, approved=False, note=note
        )

    async def _get_owned_run(
        self, workflow_id: UUID, run_id: UUID, user_id: UUID
    ) -> DBWorkflowRun:
        await self.workflow_service.get_owned_workflow(workflow_id, user_id)
        run = await run_repo.get_workflow_run_by_id(self.db, run_id)
        if run is None or run.workflow_id != workflow_id:
            raise NotFoundError(message="Workflow run not found")
        return run

    async def _decide(
        self,
        workflow_id: UUID,
        run_id: UUID,
        approval_id: UUID,
        user_id: UUID,
        *,
        approved: bool,
        note: str | None,
    ) -> DBApprovalRequest:
        run = await self._get_owned_run(workflow_id, run_id, user_id)
        if run.status != WorkflowRunStatus.PAUSED.value:
            raise WorkflowApprovalConflictError(
                message="Workflow run must be paused before deciding approval.",
                code="WORKFLOW_RUN_NOT_PAUSED",
            )
        db_approval = await approval_repo.get_approval_request_by_id_for_update(
            self.db, approval_id
        )
        if db_approval is None or db_approval.run_id != run_id:
            raise NotFoundError(message="Approval request not found")

        approval = _approval_from_row(db_approval)
        try:
            if approved:
                approval.approve(decided_by=user_id, note=note)
            else:
                approval.reject(decided_by=user_id, note=note)
        except ApprovalRequestTransitionError as exception:
            raise WorkflowApprovalConflictError(
                message="Approval request has already been decided.",
                code="APPROVAL_ALREADY_DECIDED",
            ) from exception
        updated = await approval_repo.update_approval_request_state(
            self.db, db_approval=db_approval, approval=approval
        )
        await self.db.commit()
        return updated


def _approval_from_row(row: DBApprovalRequest) -> ApprovalRequest:
    values: dict[str, Any] = {
        "id": row.id,
        "run_id": row.run_id,
        "workflow_revision": row.workflow_revision,
        "node_id": row.node_id,
        "prompt": row.prompt,
        "status": row.status,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
        "decided_by": row.decided_by,
        "decision_note": row.decision_note,
    }
    return deserialize_approval_request(values)
