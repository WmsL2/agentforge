"""Workspace-scoped knowledge document persistence primitives."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import KnowledgeDocument
from app.services.knowledge.document_parser import ParsedDocument


async def create(
    db: AsyncSession,
    *,
    document_id: UUID,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    created_by_user_id: UUID,
    filename: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    storage_path: str,
    parsed: ParsedDocument,
) -> KnowledgeDocument:
    document = KnowledgeDocument(
        id=document_id,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        created_by_user_id=created_by_user_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=sha256,
        storage_path=storage_path,
        parse_status=parsed.status,
        parse_error_code=parsed.error_code,
        parsed_content=parsed.content,
        page_count=parsed.page_count,
        parse_metadata=parsed.metadata,
    )
    db.add(document)
    await db.flush()
    await db.refresh(document)
    return document


async def get_scoped(
    db: AsyncSession, *, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID
) -> KnowledgeDocument | None:
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.workspace_id == workspace_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
            KnowledgeDocument.id == document_id,
        )
    )
    return result.scalar_one_or_none()


async def list_scoped(
    db: AsyncSession, *, workspace_id: UUID, knowledge_base_id: UUID, skip: int, limit: int
) -> list[KnowledgeDocument]:
    result = await db.execute(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.workspace_id == workspace_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
        )
        .order_by(KnowledgeDocument.created_at.asc(), KnowledgeDocument.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_scoped(db: AsyncSession, *, workspace_id: UUID, knowledge_base_id: UUID) -> int:
    value = await db.scalar(
        select(func.count())
        .select_from(KnowledgeDocument)
        .where(
            KnowledgeDocument.workspace_id == workspace_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
        )
    )
    return value or 0


async def delete(db: AsyncSession, *, document: KnowledgeDocument) -> None:
    await db.delete(document)
    await db.flush()


async def all_storage_paths(db: AsyncSession) -> set[str]:
    result = await db.scalars(select(KnowledgeDocument.storage_path))
    return set(result.all())
