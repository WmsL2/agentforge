"""Opt-in real PostgreSQL 16 + pgvector proofs for Atomic 3."""

import asyncio
import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.db.models.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeIndexJob,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.repositories import knowledge as knowledge_repo
from app.repositories import knowledge_index as index_repo
from app.repositories import workspace as workspace_repo
from app.services.knowledge.chunking import ChunkingConfig
from app.services.knowledge.embedding import EmbeddingError
from app.services.knowledge.indexing_service import KnowledgeIndexExecutor
from app.services.workspace import WorkspaceRole


class DeterministicFakeEmbeddingProvider:
    model = "text-embedding-3-small"
    dimensions = 1536

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for index, content in enumerate(texts):
            vector = [0.0] * self.dimensions
            vector[index % 2] = 1.0
            vector[2] = (len(content) % 17 + 1) / 100
            vectors.append(vector)
        return vectors


class FailingFakeEmbeddingProvider(DeterministicFakeEmbeddingProvider):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("EMBEDDING_PROVIDER_UNAVAILABLE", retryable=True)


async def _seed(factory, *, content: str = "A" * 1100 + "B" * 1100):
    user_id, document_id = uuid4(), uuid4()
    async with factory() as session, session.begin():
        session.add(User(id=user_id, email=f"index-{user_id.hex}@example.invalid"))
        await session.flush()
        workspace = await workspace_repo.create_workspace(
            session, name=f"Index {user_id.hex}", created_by_user_id=user_id
        )
        await workspace_repo.create_membership(
            session, workspace_id=workspace.id, user_id=user_id, role=WorkspaceRole.OWNER
        )
        base = await knowledge_repo.create(
            session,
            workspace_id=workspace.id,
            name="Vector index",
            description=None,
            created_by_user_id=user_id,
        )
        session.add(
            KnowledgeDocument(
                id=document_id,
                workspace_id=workspace.id,
                knowledge_base_id=base.id,
                created_by_user_id=user_id,
                filename="source.txt",
                mime_type="text/plain",
                size_bytes=len(content.encode()),
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                storage_path=f"{workspace.id}/{base.id}/{document_id}/source.txt",
                parse_status="ready",
                parsed_content=content,
                page_count=None,
                parse_metadata={"format": "txt"},
            )
        )
    return user_id, workspace.id, base.id, document_id, content


async def _create_job(factory, workspace_id, base_id, document_id, content):
    async with factory() as session, session.begin():
        job, created = await index_repo.create_pending_idempotent(
            session,
            workspace_id=workspace_id,
            knowledge_base_id=base_id,
            document_id=document_id,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            chunking_config_version="character-v1:1000:150:2500",
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        )
        assert created
        job_id = job.id
    return job_id


def _executor(factory, provider):
    return KnowledgeIndexExecutor(
        factory,
        lambda: provider,
        chunking_config=ChunkingConfig(),
        lease_duration=timedelta(minutes=5),
    )


@pytest.mark.anyio
async def test_pgvector_schema_hnsw_and_migration_contract(
    postgres_restart_session_factory,
) -> None:
    factory = postgres_restart_session_factory
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            == "0.8.7"
        )
        assert (
            await session.scalar(
                text(
                    "SELECT format_type(a.atttypid, a.atttypmod) "
                    "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                    "WHERE c.relname = 'knowledge_document_chunks' "
                    "AND a.attname = 'embedding'"
                )
            )
            == "vector(1536)"
        )
        definition = await session.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'knowledge_document_chunks_embedding_hnsw_idx'"
            )
        )
        assert "USING hnsw" in definition
        assert "vector_cosine_ops" in definition
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script.get_revision("0045_create_knowledge_vector_index")
    assert revision is not None and revision.down_revision == "0044_create_knowledge_documents"


@pytest.mark.anyio
async def test_index_is_durable_cross_session_and_cosine_sql_works(
    postgres_restart_session_factory,
) -> None:
    factory = postgres_restart_session_factory
    user_id, workspace_id, base_id, document_id, content = await _seed(factory)
    try:
        job_id = await _create_job(factory, workspace_id, base_id, document_id, content)
        assert (
            await _executor(factory, DeterministicFakeEmbeddingProvider()).execute(job_id)
        ).status == "succeeded"
        async with factory() as session:
            document = await session.get(KnowledgeDocument, document_id)
            job = await session.get(KnowledgeIndexJob, job_id)
            chunks = list(
                (
                    await session.scalars(
                        select(KnowledgeDocumentChunk)
                        .where(
                            KnowledgeDocumentChunk.document_id == document_id,
                            KnowledgeDocumentChunk.index_generation_id
                            == document.active_index_generation_id,
                        )
                        .order_by(KnowledgeDocumentChunk.chunk_index)
                    )
                ).all()
            )
            assert job.status == "succeeded" and job.chunk_count == len(chunks) >= 2
            assert all(
                chunk.content == content[chunk.start_offset : chunk.end_offset] for chunk in chunks
            )
            nearest = await session.scalar(
                select(KnowledgeDocumentChunk.id)
                .where(KnowledgeDocumentChunk.document_id == document_id)
                .order_by(KnowledgeDocumentChunk.embedding.cosine_distance([1.0] + [0.0] * 1535))
                .limit(1)
            )
            nearest_chunk = next(chunk for chunk in chunks if chunk.id == nearest)
            assert nearest_chunk.chunk_index % 2 == 0
    finally:
        async with factory() as session, session.begin():
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(User).where(User.id == user_id))


@pytest.mark.anyio
async def test_concurrent_claim_expired_lease_fencing_and_duplicate_delivery(
    postgres_restart_session_factory,
) -> None:
    factory = postgres_restart_session_factory
    user_id, workspace_id, base_id, document_id, content = await _seed(factory, content="claim")
    try:
        job_id = await _create_job(factory, workspace_id, base_id, document_id, content)

        async def claim():
            async with factory() as session, session.begin():
                return await index_repo.claim_job(
                    session, job_id=job_id, lease_duration=timedelta(minutes=1)
                )

        first, second = await asyncio.gather(claim(), claim())
        assert sum(lease is not None for lease in (first, second)) == 1
        old = first or second
        async with factory() as session, session.begin():
            await session.execute(
                update(KnowledgeIndexJob)
                .where(KnowledgeIndexJob.id == job_id)
                .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
            )
        replacement = await claim()
        assert replacement is not None and replacement.generation == old.generation + 1
        async with factory() as session, session.begin():
            assert not await index_repo.fail_job(
                session, lease=old, error_code="STALE_WORKER_MUST_NOT_WIN"
            )
        result = await _executor(factory, DeterministicFakeEmbeddingProvider()).execute(job_id)
        assert result.status == "not_claimed"
    finally:
        async with factory() as session, session.begin():
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(User).where(User.id == user_id))


@pytest.mark.anyio
async def test_failed_reindex_retains_active_generation_then_success_replaces_and_cascades(
    postgres_restart_session_factory,
) -> None:
    factory = postgres_restart_session_factory
    user_id, workspace_id, base_id, document_id, content = await _seed(factory)
    try:
        first_id = await _create_job(factory, workspace_id, base_id, document_id, content)
        assert (
            await _executor(factory, DeterministicFakeEmbeddingProvider()).execute(first_id)
        ).status == "succeeded"
        async with factory() as session:
            document = await session.get(KnowledgeDocument, document_id)
            old_generation = document.active_index_generation_id
            old_count = await session.scalar(
                select(func.count())
                .select_from(KnowledgeDocumentChunk)
                .where(KnowledgeDocumentChunk.index_generation_id == old_generation)
            )

        failed_id = await _create_job(factory, workspace_id, base_id, document_id, content)
        assert (
            await _executor(factory, FailingFakeEmbeddingProvider()).execute(failed_id)
        ).status == "failed"
        async with factory() as session:
            document = await session.get(KnowledgeDocument, document_id)
            assert document.active_index_generation_id == old_generation
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeDocumentChunk)
                    .where(KnowledgeDocumentChunk.index_generation_id == old_generation)
                )
                == old_count
            )

        replacement_id = await _create_job(factory, workspace_id, base_id, document_id, content)
        assert (
            await _executor(factory, DeterministicFakeEmbeddingProvider()).execute(replacement_id)
        ).status == "succeeded"
        async with factory() as session, session.begin():
            document = await session.get(KnowledgeDocument, document_id)
            assert document.active_index_generation_id != old_generation
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeDocumentChunk)
                    .where(KnowledgeDocumentChunk.index_generation_id == old_generation)
                )
                == 0
            )
            await session.delete(document)
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeDocumentChunk)
                    .where(KnowledgeDocumentChunk.document_id == document_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeIndexJob)
                    .where(KnowledgeIndexJob.document_id == document_id)
                )
                == 0
            )
    finally:
        async with factory() as session, session.begin():
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(User).where(User.id == user_id))


@pytest.mark.anyio
async def test_database_rejects_cross_owner_chunk(postgres_restart_session_factory) -> None:
    factory = postgres_restart_session_factory
    user_id, workspace_id, base_id, document_id, content = await _seed(factory, content="owner")
    try:
        job_id = await _create_job(factory, workspace_id, base_id, document_id, content)
        async with factory() as session:
            job = await session.get(KnowledgeIndexJob, job_id)
            bad = KnowledgeDocumentChunk(
                workspace_id=uuid4(),
                knowledge_base_id=base_id,
                document_id=document_id,
                index_generation_id=job.index_generation_id,
                chunk_index=0,
                content="x",
                start_offset=0,
                end_offset=1,
                chunk_metadata={},
                embedding_model=job.embedding_model,
                embedding=[1.0] + [0.0] * 1535,
            )
            session.add(bad)
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        async with factory() as session, session.begin():
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(User).where(User.id == user_id))
