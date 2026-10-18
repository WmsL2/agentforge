"""Authenticated workflow-run execution and history routes."""

from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, WorkflowAsyncRunSvc, WorkflowRunSvc
from app.schemas.workflow import (
    WorkflowRunCreate,
    WorkflowRunList,
    WorkflowRunRead,
    WorkflowRunStepRead,
    WorkflowTraceEventRead,
)

router = APIRouter()


@router.post(
    "/{workflow_id}/runs", response_model=WorkflowRunRead, status_code=status.HTTP_201_CREATED
)
async def execute_workflow(
    workflow_id: UUID,
    data: WorkflowRunCreate,
    workflow_run_service: WorkflowRunSvc,
    current_user: CurrentUser,
):
    return await workflow_run_service.execute_workflow(workflow_id, current_user.id, data.input)


@router.post(
    "/{workflow_id}/runs/async",
    response_model=WorkflowRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_workflow_async(
    workflow_id: UUID,
    data: WorkflowRunCreate,
    workflow_async_run_service: WorkflowAsyncRunSvc,
    current_user: CurrentUser,
    response: Response,
):
    run = await workflow_async_run_service.submit_workflow(
        workflow_id,
        current_user.id,
        data.input,
    )
    response.headers["Location"] = f"/api/v1/workflows/{workflow_id}/runs/{run.id}"
    return run


@router.get("/{workflow_id}/runs", response_model=WorkflowRunList)
async def list_workflow_runs(
    workflow_id: UUID,
    workflow_run_service: WorkflowRunSvc,
    current_user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    items, total = await workflow_run_service.list_workflow_runs(
        workflow_id, current_user.id, skip, limit
    )
    return {"items": items, "total": total}


@router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRunRead)
async def get_workflow_run(
    workflow_id: UUID,
    run_id: UUID,
    workflow_run_service: WorkflowRunSvc,
    current_user: CurrentUser,
):
    return await workflow_run_service.get_workflow_run(workflow_id, run_id, current_user.id)


@router.get("/{workflow_id}/runs/{run_id}/steps", response_model=list[WorkflowRunStepRead])
async def list_workflow_run_steps(
    workflow_id: UUID,
    run_id: UUID,
    workflow_run_service: WorkflowRunSvc,
    current_user: CurrentUser,
):
    return await workflow_run_service.list_workflow_run_steps(workflow_id, run_id, current_user.id)


@router.get("/{workflow_id}/runs/{run_id}/trace", response_model=list[WorkflowTraceEventRead])
async def list_workflow_trace_events(
    workflow_id: UUID,
    run_id: UUID,
    workflow_run_service: WorkflowRunSvc,
    current_user: CurrentUser,
):
    return await workflow_run_service.list_workflow_trace_events(
        workflow_id, run_id, current_user.id
    )
