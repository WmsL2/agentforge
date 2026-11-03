"""Workspace-scoped knowledge base CRUD routes."""

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, KnowledgeBaseSvc
from app.schemas.knowledge import (
    KnowledgeBaseCreate,
    KnowledgeBaseList,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
)

router = APIRouter()


@router.post("", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    workspace_id: UUID,
    data: KnowledgeBaseCreate,
    knowledge_base_service: KnowledgeBaseSvc,
    current_user: CurrentUser,
):
    return await knowledge_base_service.create_knowledge_base(workspace_id, current_user.id, data)


@router.get("", response_model=KnowledgeBaseList)
async def list_knowledge_bases(
    workspace_id: UUID,
    knowledge_base_service: KnowledgeBaseSvc,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    items, total = await knowledge_base_service.list_knowledge_bases(
        workspace_id, current_user.id, skip=skip, limit=limit
    )
    return {"items": items, "total": total}


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseRead)
async def get_knowledge_base(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    knowledge_base_service: KnowledgeBaseSvc,
    current_user: CurrentUser,
):
    return await knowledge_base_service.get_knowledge_base(
        workspace_id, knowledge_base_id, current_user.id
    )


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseRead)
async def update_knowledge_base(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    data: KnowledgeBaseUpdate,
    knowledge_base_service: KnowledgeBaseSvc,
    current_user: CurrentUser,
):
    return await knowledge_base_service.update_knowledge_base(
        workspace_id, knowledge_base_id, current_user.id, data
    )


@router.delete("/{knowledge_base_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_knowledge_base(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    knowledge_base_service: KnowledgeBaseSvc,
    current_user: CurrentUser,
):
    await knowledge_base_service.delete_knowledge_base(
        workspace_id, knowledge_base_id, current_user.id
    )
