"""Workspace-scoped knowledge document routes."""

from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, KnowledgeDocumentSvc
from app.schemas.knowledge import (
    KnowledgeDocumentContent,
    KnowledgeDocumentList,
    KnowledgeDocumentRead,
)

router = APIRouter()


@router.post("", response_model=KnowledgeDocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_service: KnowledgeDocumentSvc,
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    return await document_service.upload_document(
        workspace_id, knowledge_base_id, current_user.id, file
    )


@router.get("", response_model=KnowledgeDocumentList)
async def list_documents(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_service: KnowledgeDocumentSvc,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    items, total = await document_service.list_documents(
        workspace_id, knowledge_base_id, current_user.id, skip=skip, limit=limit
    )
    return {"items": items, "total": total}


@router.get("/{document_id}", response_model=KnowledgeDocumentRead)
async def get_document(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
    document_service: KnowledgeDocumentSvc,
    current_user: CurrentUser,
):
    return await document_service.get_document(
        workspace_id, knowledge_base_id, document_id, current_user.id
    )


@router.get("/{document_id}/content", response_model=KnowledgeDocumentContent)
async def get_document_content(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
    document_service: KnowledgeDocumentSvc,
    current_user: CurrentUser,
):
    document = await document_service.get_content(
        workspace_id, knowledge_base_id, document_id, current_user.id
    )
    return {
        "document_id": document_id,
        "content": document.parsed_content,
        "page_count": document.page_count,
        "parse_metadata": document.parse_metadata,
    }


@router.get("/{document_id}/download", response_class=FileResponse)
async def download_document(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
    document_service: KnowledgeDocumentSvc,
    current_user: CurrentUser,
):
    document, path = await document_service.get_download(
        workspace_id, knowledge_base_id, document_id, current_user.id
    )
    return FileResponse(
        path,
        media_type=document.mime_type,
        filename=document.filename,
        content_disposition_type="attachment",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_document(
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
    document_service: KnowledgeDocumentSvc,
    current_user: CurrentUser,
):
    await document_service.delete_document(
        workspace_id, knowledge_base_id, document_id, current_user.id
    )
