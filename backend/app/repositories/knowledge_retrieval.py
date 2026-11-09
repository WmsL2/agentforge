"""Read-only, workspace-scoped pgvector retrieval primitives."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeIndexJob,
)


@dataclass(frozen=True)
class ActiveIndexProfile:
    embedding_model: str
    embedding_dimensions: int
    document_count: int


@dataclass(frozen=True)
class KnowledgeRetrievalRow:
    chunk_id: UUID
    document_id: UUID
    knowledge_base_id: UUID
    filename: str
    chunk_index: int
    content: str
    start_offset: int
    end_offset: int
    page_start: int | None
    page_end: int | None
    similarity_score: float


async def list_active_index_profiles(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    statement_timeout_ms: int,
) -> list[ActiveIndexProfile]:
    """Return model identities for currently active, successfully committed generations."""
    await _set_statement_timeout(db, statement_timeout_ms)
    rows = (
        await db.execute(
            select(
                KnowledgeIndexJob.embedding_model,
                KnowledgeIndexJob.embedding_dimensions,
                func.count(KnowledgeDocument.id.distinct()).label("document_count"),
            )
            .select_from(KnowledgeDocument)
            .join(
                KnowledgeIndexJob,
                and_(
                    KnowledgeIndexJob.workspace_id == KnowledgeDocument.workspace_id,
                    KnowledgeIndexJob.knowledge_base_id == KnowledgeDocument.knowledge_base_id,
                    KnowledgeIndexJob.document_id == KnowledgeDocument.id,
                    KnowledgeIndexJob.index_generation_id
                    == KnowledgeDocument.active_index_generation_id,
                    KnowledgeIndexJob.status == "succeeded",
                ),
            )
            .where(
                KnowledgeDocument.workspace_id == workspace_id,
                KnowledgeDocument.knowledge_base_id == knowledge_base_id,
                KnowledgeDocument.parse_status == "ready",
                KnowledgeDocument.active_index_generation_id.is_not(None),
            )
            .group_by(
                KnowledgeIndexJob.embedding_model,
                KnowledgeIndexJob.embedding_dimensions,
            )
            .order_by(
                KnowledgeIndexJob.embedding_model,
                KnowledgeIndexJob.embedding_dimensions,
            )
        )
    ).all()
    return [
        ActiveIndexProfile(row.embedding_model, row.embedding_dimensions, row.document_count)
        for row in rows
    ]


async def search_active_chunks(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    query_vector: list[float],
    embedding_model: str,
    embedding_dimensions: int,
    top_k: int,
    min_score: float | None,
    statement_timeout_ms: int,
) -> list[KnowledgeRetrievalRow]:
    """Search only scoped chunks belonging to each document's active generation."""
    await _set_statement_timeout(db, statement_timeout_ms)
    # pgvector 0.8+ continues scanning an approximate index after filtered rows are
    # discarded. strict_order preserves exact distance ordering of returned rows.
    await db.execute(select(func.set_config("hnsw.iterative_scan", "strict_order", True)))

    distance = KnowledgeDocumentChunk.embedding.cosine_distance(query_vector)
    similarity = (1.0 - distance).label("similarity_score")
    statement = (
        select(
            KnowledgeDocumentChunk.id.label("chunk_id"),
            KnowledgeDocumentChunk.document_id,
            KnowledgeDocumentChunk.knowledge_base_id,
            KnowledgeDocument.filename,
            KnowledgeDocumentChunk.chunk_index,
            KnowledgeDocumentChunk.content,
            KnowledgeDocumentChunk.start_offset,
            KnowledgeDocumentChunk.end_offset,
            KnowledgeDocumentChunk.page_start,
            KnowledgeDocumentChunk.page_end,
            similarity,
        )
        .select_from(KnowledgeDocumentChunk)
        .join(
            KnowledgeDocument,
            and_(
                KnowledgeDocument.workspace_id == KnowledgeDocumentChunk.workspace_id,
                KnowledgeDocument.knowledge_base_id == KnowledgeDocumentChunk.knowledge_base_id,
                KnowledgeDocument.id == KnowledgeDocumentChunk.document_id,
                KnowledgeDocument.active_index_generation_id
                == KnowledgeDocumentChunk.index_generation_id,
            ),
        )
        .join(
            KnowledgeIndexJob,
            and_(
                KnowledgeIndexJob.workspace_id == KnowledgeDocument.workspace_id,
                KnowledgeIndexJob.knowledge_base_id == KnowledgeDocument.knowledge_base_id,
                KnowledgeIndexJob.document_id == KnowledgeDocument.id,
                KnowledgeIndexJob.index_generation_id
                == KnowledgeDocument.active_index_generation_id,
                KnowledgeIndexJob.status == "succeeded",
            ),
        )
        .where(
            KnowledgeDocumentChunk.workspace_id == workspace_id,
            KnowledgeDocumentChunk.knowledge_base_id == knowledge_base_id,
            KnowledgeDocument.workspace_id == workspace_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
            KnowledgeDocument.parse_status == "ready",
            KnowledgeDocument.active_index_generation_id.is_not(None),
            KnowledgeDocumentChunk.embedding_model == embedding_model,
            KnowledgeIndexJob.embedding_model == embedding_model,
            KnowledgeIndexJob.embedding_dimensions == embedding_dimensions,
        )
        .order_by(
            distance.asc(),
            KnowledgeDocumentChunk.document_id.asc(),
            KnowledgeDocumentChunk.chunk_index.asc(),
            KnowledgeDocumentChunk.id.asc(),
        )
        .limit(top_k)
    )
    if min_score is not None:
        statement = statement.where(distance <= 1.0 - min_score)

    rows = (await db.execute(statement)).all()
    return [
        KnowledgeRetrievalRow(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            knowledge_base_id=row.knowledge_base_id,
            filename=row.filename,
            chunk_index=row.chunk_index,
            content=row.content,
            start_offset=row.start_offset,
            end_offset=row.end_offset,
            page_start=row.page_start,
            page_end=row.page_end,
            similarity_score=float(row.similarity_score),
        )
        for row in rows
    ]


async def _set_statement_timeout(db: AsyncSession, milliseconds: int) -> None:
    await db.execute(select(func.set_config("statement_timeout", str(milliseconds), True)))
