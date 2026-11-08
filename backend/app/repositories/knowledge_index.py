"""Persistence primitives for durable, fenced knowledge indexing."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import KnowledgeDocument, KnowledgeDocumentChunk, KnowledgeIndexJob
from app.services.knowledge.chunking import DocumentChunk


@dataclass(frozen=True)
class IndexLease:
    job_id: UUID
    claim_token: UUID
    generation: int
    expires_at: datetime


async def create_pending_idempotent(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
    embedding_model: str,
    embedding_dimensions: int,
    chunking_config_version: str,
    content_sha256: str,
) -> tuple[KnowledgeIndexJob, bool]:
    values = {
        "id": uuid4(),
        "workspace_id": workspace_id,
        "knowledge_base_id": knowledge_base_id,
        "document_id": document_id,
        "index_generation_id": uuid4(),
        "status": "pending",
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions,
        "chunking_config_version": chunking_config_version,
        "content_sha256": content_sha256,
    }
    created_id = await db.scalar(
        insert(KnowledgeIndexJob)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[KnowledgeIndexJob.document_id],
            index_where=KnowledgeIndexJob.status.in_(("pending", "running")),
        )
        .returning(KnowledgeIndexJob.id)
    )
    if created_id is not None:
        job = await db.get(KnowledgeIndexJob, created_id)
        assert job is not None
        return job, True
    active = await get_active_job(db, document_id=document_id)
    if active is None:
        raise RuntimeError("active index job disappeared during idempotent create")
    return active, False


async def get_active_job(db: AsyncSession, *, document_id: UUID) -> KnowledgeIndexJob | None:
    return await db.scalar(
        select(KnowledgeIndexJob)
        .where(
            KnowledgeIndexJob.document_id == document_id,
            KnowledgeIndexJob.status.in_(("pending", "running")),
        )
        .order_by(KnowledgeIndexJob.created_at.desc())
        .limit(1)
    )


async def get_latest_job_scoped(
    db: AsyncSession, *, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID
) -> KnowledgeIndexJob | None:
    return await db.scalar(
        select(KnowledgeIndexJob)
        .where(
            KnowledgeIndexJob.workspace_id == workspace_id,
            KnowledgeIndexJob.knowledge_base_id == knowledge_base_id,
            KnowledgeIndexJob.document_id == document_id,
        )
        .order_by(KnowledgeIndexJob.created_at.desc(), KnowledgeIndexJob.id.desc())
        .limit(1)
    )


async def get_job_by_generation(
    db: AsyncSession, *, document_id: UUID, generation_id: UUID | None
) -> KnowledgeIndexJob | None:
    if generation_id is None:
        return None
    return await db.scalar(
        select(KnowledgeIndexJob).where(
            KnowledgeIndexJob.document_id == document_id,
            KnowledgeIndexJob.index_generation_id == generation_id,
            KnowledgeIndexJob.status == "succeeded",
        )
    )


async def count_active_chunks(db: AsyncSession, document: KnowledgeDocument) -> int:
    if document.active_index_generation_id is None:
        return 0
    value = await db.scalar(
        select(func.count())
        .select_from(KnowledgeDocumentChunk)
        .where(
            KnowledgeDocumentChunk.document_id == document.id,
            KnowledgeDocumentChunk.index_generation_id == document.active_index_generation_id,
        )
    )
    return value or 0


async def claim_job(
    db: AsyncSession, *, job_id: UUID, lease_duration: timedelta
) -> IndexLease | None:
    expired = and_(
        KnowledgeIndexJob.status == "running",
        KnowledgeIndexJob.lease_expires_at <= func.clock_timestamp(),
    )
    result = await db.execute(
        update(KnowledgeIndexJob)
        .where(
            KnowledgeIndexJob.id == job_id,
            or_(KnowledgeIndexJob.status == "pending", expired),
        )
        .values(
            status="running",
            attempt_count=KnowledgeIndexJob.attempt_count + 1,
            claim_token=uuid4(),
            claim_generation=KnowledgeIndexJob.claim_generation + 1,
            lease_expires_at=func.clock_timestamp() + lease_duration,
            started_at=func.coalesce(KnowledgeIndexJob.started_at, func.clock_timestamp()),
            error_code=None,
        )
        .returning(
            KnowledgeIndexJob.id,
            KnowledgeIndexJob.claim_token,
            KnowledgeIndexJob.claim_generation,
            KnowledgeIndexJob.lease_expires_at,
        )
        .execution_options(synchronize_session=False)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return IndexLease(row.id, row.claim_token, row.claim_generation, row.lease_expires_at)


async def load_claimed_source(
    db: AsyncSession, lease: IndexLease
) -> tuple[KnowledgeIndexJob, KnowledgeDocument] | None:
    row = (
        await db.execute(
            select(KnowledgeIndexJob, KnowledgeDocument)
            .join(
                KnowledgeDocument,
                and_(
                    KnowledgeDocument.id == KnowledgeIndexJob.document_id,
                    KnowledgeDocument.workspace_id == KnowledgeIndexJob.workspace_id,
                    KnowledgeDocument.knowledge_base_id == KnowledgeIndexJob.knowledge_base_id,
                ),
            )
            .where(_valid_lease(lease))
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


async def complete_job(
    db: AsyncSession,
    *,
    lease: IndexLease,
    chunks: list[DocumentChunk],
    vectors: list[list[float]],
) -> bool:
    job = await db.scalar(
        select(KnowledgeIndexJob).where(KnowledgeIndexJob.id == lease.job_id).with_for_update()
    )
    if job is None or not await db.scalar(select(KnowledgeIndexJob.id).where(_valid_lease(lease))):
        return False
    document = await db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.id == job.document_id,
            KnowledgeDocument.workspace_id == job.workspace_id,
            KnowledgeDocument.knowledge_base_id == job.knowledge_base_id,
        )
        .with_for_update()
    )
    if document is None:
        return False
    db.add_all(
        [
            KnowledgeDocumentChunk(
                workspace_id=job.workspace_id,
                knowledge_base_id=job.knowledge_base_id,
                document_id=job.document_id,
                index_generation_id=job.index_generation_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                chunk_metadata=chunk.metadata,
                embedding_model=job.embedding_model,
                embedding=vector,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
    )
    await db.flush()
    document.active_index_generation_id = job.index_generation_id
    await db.execute(
        delete(KnowledgeDocumentChunk).where(
            KnowledgeDocumentChunk.document_id == job.document_id,
            KnowledgeDocumentChunk.index_generation_id != job.index_generation_id,
        )
    )
    job.status = "succeeded"
    job.chunk_count = len(chunks)
    job.claim_token = None
    job.lease_expires_at = None
    job.error_code = None
    job.finished_at = await db.scalar(select(func.clock_timestamp()))
    await db.flush()
    return True


async def fail_job(db: AsyncSession, *, lease: IndexLease, error_code: str) -> bool:
    result = await db.execute(
        update(KnowledgeIndexJob)
        .where(_valid_lease(lease))
        .values(
            status="failed",
            claim_token=None,
            lease_expires_at=None,
            error_code=error_code,
            finished_at=func.clock_timestamp(),
        )
        .returning(KnowledgeIndexJob.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


async def renew_job(db: AsyncSession, *, lease: IndexLease, lease_duration: timedelta) -> bool:
    result = await db.execute(
        update(KnowledgeIndexJob)
        .where(_valid_lease(lease))
        .values(lease_expires_at=func.clock_timestamp() + lease_duration)
        .returning(KnowledgeIndexJob.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


async def list_recoverable_job_ids(
    db: AsyncSession, *, limit: int, redispatch_delay: timedelta
) -> list[UUID]:
    due = or_(
        KnowledgeIndexJob.last_dispatched_at.is_(None),
        KnowledgeIndexJob.last_dispatched_at <= func.clock_timestamp() - redispatch_delay,
    )
    recoverable = or_(
        KnowledgeIndexJob.status == "pending",
        and_(
            KnowledgeIndexJob.status == "running",
            KnowledgeIndexJob.lease_expires_at <= func.clock_timestamp(),
        ),
    )
    jobs = list(
        (
            await db.scalars(
                select(KnowledgeIndexJob)
                .where(recoverable, due)
                .order_by(KnowledgeIndexJob.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    now = await db.scalar(select(func.clock_timestamp()))
    for job in jobs:
        job.last_dispatched_at = now
    await db.flush()
    return [job.id for job in jobs]


def _valid_lease(lease: IndexLease):
    return and_(
        KnowledgeIndexJob.id == lease.job_id,
        KnowledgeIndexJob.status == "running",
        KnowledgeIndexJob.claim_token == lease.claim_token,
        KnowledgeIndexJob.claim_generation == lease.generation,
        KnowledgeIndexJob.lease_expires_at > func.clock_timestamp(),
    )
