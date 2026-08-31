"""Workflow CRUD routes."""

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, WorkflowSvc
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowGraphSchema,
    WorkflowList,
    WorkflowRead,
    WorkflowUpdate,
    WorkflowValidationRead,
)

router = APIRouter()


@router.post("/validate", response_model=WorkflowValidationRead)
async def validate(data: WorkflowGraphSchema, workflow_service: WorkflowSvc, _: CurrentUser):
    result = workflow_service.validate_definition(data)
    return {
        "is_valid": result.is_valid,
        "issues": [
            {"code": i.code, "message": i.message, "node_id": i.node_id, "edge_id": i.edge_id}
            for i in result.issues
        ],
    }


@router.get("", response_model=WorkflowList)
async def list_workflows(
    workflow_service: WorkflowSvc,
    current_user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    items, total = await workflow_service.list_workflows(current_user.id, skip, limit)
    return {"items": items, "total": total}


@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create(data: WorkflowCreate, workflow_service: WorkflowSvc, current_user: CurrentUser):
    return await workflow_service.create_workflow(current_user.id, data)


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get(workflow_id: UUID, workflow_service: WorkflowSvc, current_user: CurrentUser):
    return await workflow_service.get_workflow(workflow_id, current_user.id)


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def update(
    workflow_id: UUID,
    data: WorkflowUpdate,
    workflow_service: WorkflowSvc,
    current_user: CurrentUser,
):
    return await workflow_service.update_workflow(workflow_id, current_user.id, data)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete(workflow_id: UUID, workflow_service: WorkflowSvc, current_user: CurrentUser):
    await workflow_service.delete_workflow(workflow_id, current_user.id)
