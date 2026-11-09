"""Workspace-scoped semantic knowledge retrieval route."""

from uuid import UUID

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, KnowledgeRetrievalSvc
from app.schemas.knowledge import KnowledgeSearchRequest, KnowledgeSearchResponse

router = APIRouter()


@router.post("", response_model=KnowledgeSearchResponse)
async def search_knowledge_base(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    data: KnowledgeSearchRequest,
    retrieval_service: KnowledgeRetrievalSvc,
    current_user: CurrentUser,
    response: Response,
):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return await retrieval_service.search(
        workspace_id,
        knowledge_base_id,
        current_user.id,
        data.query,
        data.top_k,
        data.min_score,
    )
