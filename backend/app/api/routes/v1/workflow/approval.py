"""Authenticated workflow approval query and decision routes."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import (
    CurrentUser,
    WorkflowApprovalAsyncSvc,
    WorkflowApprovalSvc,
    WorkflowExecutionDispatcherDep,
)
from app.schemas.workflow import ApprovalDecisionRequest, ApprovalRequestRead

router = APIRouter()


@router.get("/{workflow_id}/runs/{run_id}/approvals/pending", response_model=ApprovalRequestRead)
async def get_pending_approval(
    workflow_id: UUID,
    run_id: UUID,
    approval_service: WorkflowApprovalSvc,
    current_user: CurrentUser,
):
    return await approval_service.get_pending_approval(workflow_id, run_id, current_user.id)


@router.post(
    "/{workflow_id}/runs/{run_id}/approvals/{approval_id}/approve",
    response_model=ApprovalRequestRead,
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
    "/{workflow_id}/runs/{run_id}/approvals/{approval_id}/approve/async",
    response_model=ApprovalRequestRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_async(
    workflow_id: UUID,
    run_id: UUID,
    approval_id: UUID,
    data: ApprovalDecisionRequest,
    response: Response,
    approval_service: WorkflowApprovalAsyncSvc,
    dispatcher: WorkflowExecutionDispatcherDep,
    current_user: CurrentUser,
):
    approval = await approval_service.approve_async(
        workflow_id,
        run_id,
        approval_id,
        current_user.id,
        dispatcher,
        note=data.note,
    )
    response.headers["Location"] = f"/api/v1/workflows/{workflow_id}/runs/{run_id}"
    return approval


@router.post(
    "/{workflow_id}/runs/{run_id}/approvals/{approval_id}/reject",
    response_model=ApprovalRequestRead,
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
