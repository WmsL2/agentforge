"""Authenticated workflow approval query and decision routes."""

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, WorkflowApprovalSvc
from app.schemas.workflow import ApprovalDecisionRequest, ApprovalRequestRead

router = APIRouter()


@router.get(
    "/{workflow_id}/runs/{run_id}/approvals/pending", response_model=ApprovalRequestRead
)
async def get_pending_approval(
    workflow_id: UUID,
    run_id: UUID,
    approval_service: WorkflowApprovalSvc,
    current_user: CurrentUser,
):
    return await approval_service.get_pending_approval(workflow_id, run_id, current_user.id)


@router.post(
    "/{workflow_id}/runs/{run_id}/approvals/{approval_id}/approve", response_model=ApprovalRequestRead
)
async def approve(
    workflow_id: UUID,
    run_id: UUID,
    approval_id: UUID,
    data: ApprovalDecisionRequest,
    approval_service: WorkflowApprovalSvc,
    current_user: CurrentUser,
):
    return await approval_service.approve(
        workflow_id, run_id, approval_id, current_user.id, note=data.note
    )


@router.post(
    "/{workflow_id}/runs/{run_id}/approvals/{approval_id}/reject", response_model=ApprovalRequestRead
)
async def reject(
    workflow_id: UUID,
    run_id: UUID,
    approval_id: UUID,
    data: ApprovalDecisionRequest,
    approval_service: WorkflowApprovalSvc,
    current_user: CurrentUser,
):
    return await approval_service.reject(
        workflow_id, run_id, approval_id, current_user.id, note=data.note
    )
