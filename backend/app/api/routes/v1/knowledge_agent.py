"""Authenticated workspace-scoped Knowledge Agent endpoint."""

from uuid import UUID

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, KnowledgeAgentSvc
from app.schemas.knowledge import KnowledgeAskRequest, KnowledgeAskResponse

router = APIRouter()


@router.post("", response_model=KnowledgeAskResponse)
async def ask_knowledge_base(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    data: KnowledgeAskRequest,
    agent_service: KnowledgeAgentSvc,
    current_user: CurrentUser,
    response: Response,
):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return await agent_service.ask(
        workspace_id,
        knowledge_base_id,
        current_user.id,
        data.question,
    )
