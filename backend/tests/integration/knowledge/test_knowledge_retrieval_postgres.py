"""Opt-in PostgreSQL 16 + pgvector proofs for Atomic 4 retrieval."""

import hashlib
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text

from app.core.config import settings
from app.core.exceptions import ContentUnavailableError, NotFoundError
from app.db.models.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeIndexJob,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.repositories import knowledge as knowledge_repo
from app.repositories import workspace as workspace_repo
from app.services.knowledge.retrieval_service import KnowledgeRetrievalService
from app.services.workspace import WorkspaceRole

DATABASE = "agentforge_v011_atomic4_verify"
MODEL = "text-embedding-3-small"
DIMENSIONS = 1536


class DeterministicQueryProvider:
    model = MODEL
    dimensions = DIMENSIONS

    def __init__(self, vector: list[float]):
        self.vector = vector
        self.calls: list[list[str]] = []
        self.closed = False

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [self.vector.copy() for _ in texts]

    async def aclose(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class Scope:
    owner_id: UUID
    workspace_id: UUID
    knowledge_base_id: UUID


def _unit_vector(first: float = 1.0, second: float = 0.0) -> list[float]:
    return [first, second] + [0.0] * (DIMENSIONS - 2)


def _service(factory, provider: DeterministicQueryProvider) -> KnowledgeRetrievalService:
    return KnowledgeRetrievalService(
        cast(Any, factory),
        lambda: provider,
        embedding_model=MODEL,
        embedding_dimensions=DIMENSIONS,
        embedding_timeout_seconds=2,
        db_statement_timeout_ms=5000,
    )


async def _create_scope(factory, *, name: str) -> Scope:
    owner_id = uuid4()
    async with factory() as session, session.begin():
        session.add(User(id=owner_id, email=f"retrieval-{owner_id.hex}@example.invalid"))
        await session.flush()
        workspace = await workspace_repo.create_workspace(
            session, name=name, created_by_user_id=owner_id
        )
        await workspace_repo.create_membership(
            session,
            workspace_id=workspace.id,
            user_id=owner_id,
            role=WorkspaceRole.OWNER,
        )
        knowledge_base = await knowledge_repo.create(
            session,
            workspace_id=workspace.id,
            name=f"{name} knowledge",
            description=None,
            created_by_user_id=owner_id,
        )
    return Scope(owner_id, workspace.id, knowledge_base.id)


async def _add_document_generation(
    session,
    *,
    scope: Scope,
    filename: str,
    vector: list[float],
    content: str,
    model: str = MODEL,
    document_id: UUID | None = None,
    generation_id: UUID | None = None,
    make_active: bool = True,
) -> tuple[UUID, UUID, UUID]:
    document_id = document_id or uuid4()
    generation_id = generation_id or uuid4()
    document = await session.get(KnowledgeDocument, document_id)
    if document is None:
        document = KnowledgeDocument(
            id=document_id,
            workspace_id=scope.workspace_id,
            knowledge_base_id=scope.knowledge_base_id,
            created_by_user_id=scope.owner_id,
            filename=filename,
            mime_type="text/plain",
            size_bytes=len(content.encode()),
            sha256=hashlib.sha256(content.encode()).hexdigest(),
            storage_path=(
                f"{scope.workspace_id}/{scope.knowledge_base_id}/{document_id}/{filename}"
            ),
            parse_status="ready",
            parsed_content=content,
            page_count=1,
            parse_metadata={"format": "txt"},
        )
        session.add(document)
        await session.flush()
    session.add(
        KnowledgeIndexJob(
            workspace_id=scope.workspace_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=document_id,
            index_generation_id=generation_id,
            status="succeeded",
            embedding_model=model,
            embedding_dimensions=DIMENSIONS,
            chunking_config_version="character-v1:1000:150:2500",
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            attempt_count=1,
            claim_generation=1,
            chunk_count=1,
        )
    )
    chunk_id = uuid4()
    session.add(
        KnowledgeDocumentChunk(
            id=chunk_id,
            workspace_id=scope.workspace_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=document_id,
            index_generation_id=generation_id,
            chunk_index=0,
            content=content,
            start_offset=0,
            end_offset=len(content),
            page_start=1,
            page_end=1,
            chunk_metadata={},
            embedding_model=model,
            embedding=vector,
        )
    )
    if make_active:
        document.active_index_generation_id = generation_id
    await session.flush()
    return document_id, generation_id, chunk_id


async def _cleanup(factory, scopes: list[Scope]) -> None:
    async with factory() as session, session.begin():
        for scope in scopes:
            await session.execute(delete(Workspace).where(Workspace.id == scope.workspace_id))
            await session.execute(delete(User).where(User.id == scope.owner_id))


@pytest.fixture
def retrieval_factory(postgres_restart_session_factory):
    if settings.POSTGRES_DB != DATABASE:
        pytest.skip(f"Atomic 4 retrieval proof requires POSTGRES_DB={DATABASE}.")
    return postgres_restart_session_factory


@pytest.mark.anyio
async def test_scoped_top_k_min_score_chinese_query_and_hnsw_filtered_candidates(
    retrieval_factory,
) -> None:
    factory = retrieval_factory
    target = await _create_scope(factory, name="Target")
    other_workspace = await _create_scope(factory, name="Other workspace")
    same_workspace_other_base: Scope | None = None
    try:
        async with factory() as session, session.begin():
            second_base = await knowledge_repo.create(
                session,
                workspace_id=target.workspace_id,
                name="Other base",
                description=None,
                created_by_user_id=target.owner_id,
            )
            same_workspace_other_base = Scope(target.owner_id, target.workspace_id, second_base.id)
            _, _, exact_chunk = await _add_document_generation(
                session,
                scope=target,
                filename="exact.txt",
                vector=_unit_vector(),
                content="草鱼体重与体长呈相关关系",
            )
            _, _, second_chunk = await _add_document_generation(
                session,
                scope=target,
                filename="second.txt",
                vector=_unit_vector(0.8, 0.6),
                content="第二个合格片段",
            )
            await _add_document_generation(
                session,
                scope=target,
                filename="orthogonal.txt",
                vector=_unit_vector(0.0, 1.0),
                content="正交片段",
            )
            # Closer global candidates in both forbidden scopes must never consume target Top-K.
            for index in range(24):
                await _add_document_generation(
                    session,
                    scope=other_workspace,
                    filename=f"foreign-{index}.txt",
                    vector=_unit_vector(),
                    content=f"foreign {index}",
                )
            await _add_document_generation(
                session,
                scope=same_workspace_other_base,
                filename="other-base.txt",
                vector=_unit_vector(),
                content="other base",
            )
        async with factory() as session:
            before_jobs = await session.scalar(select(func.count()).select_from(KnowledgeIndexJob))
            before_chunks = await session.scalar(
                select(func.count()).select_from(KnowledgeDocumentChunk)
            )

        provider = DeterministicQueryProvider(_unit_vector())
        result = await _service(factory, provider).search(
            target.workspace_id,
            target.knowledge_base_id,
            target.owner_id,
            "草鱼体重与体长的关系",
            2,
            None,
        )
        assert [item.chunk_id for item in result.results] == [exact_chunk, second_chunk]
        assert result.results[0].similarity_score == pytest.approx(1.0)
        assert result.results[1].similarity_score == pytest.approx(0.8)
        assert all(item.knowledge_base_id == target.knowledge_base_id for item in result.results)
        assert provider.calls == [["草鱼体重与体长的关系"]] and provider.closed

        threshold = await _service(factory, DeterministicQueryProvider(_unit_vector())).search(
            target.workspace_id,
            target.knowledge_base_id,
            target.owner_id,
            "threshold",
            20,
            0.9,
        )
        assert [item.chunk_id for item in threshold.results] == [exact_chunk]

        async with factory() as session:
            assert (
                await session.scalar(select(func.count()).select_from(KnowledgeIndexJob))
                == before_jobs
            )
            assert (
                await session.scalar(select(func.count()).select_from(KnowledgeDocumentChunk))
                == before_chunks
            )
            assert (
                await session.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
                == "0.8.7"
            )
            index_definition = await session.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'knowledge_document_chunks_embedding_hnsw_idx'"
                )
            )
            assert "USING hnsw" in index_definition and "vector_cosine_ops" in index_definition

            await session.execute(text("SET LOCAL enable_seqscan = off"))
            await session.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
            vector_literal = "[" + ",".join(str(value) for value in _unit_vector()) + "]"
            scoped_plan = "\n".join(
                (
                    await session.execute(
                        text(
                            "EXPLAIN (COSTS OFF) "
                            "SELECT c.id FROM knowledge_document_chunks c "
                            "JOIN knowledge_documents d ON d.workspace_id = c.workspace_id "
                            "AND d.knowledge_base_id = c.knowledge_base_id "
                            "AND d.id = c.document_id "
                            "AND d.active_index_generation_id = c.index_generation_id "
                            "WHERE c.workspace_id = :workspace_id "
                            "AND c.knowledge_base_id = :base_id "
                            "ORDER BY c.embedding <=> CAST(:query_vector AS vector) LIMIT 2"
                        ),
                        {
                            "workspace_id": target.workspace_id,
                            "base_id": target.knowledge_base_id,
                            "query_vector": vector_literal,
                        },
                    )
                ).scalars()
            )
            assert "knowledge_document_chunks_embedding_hnsw_idx" in scoped_plan or (
                "knowledge_document_chunks_owner_generation_idx" in scoped_plan
                and "Sort Key" in scoped_plan
            )
            hnsw_plan = "\n".join(
                (
                    await session.execute(
                        text(
                            "EXPLAIN (COSTS OFF) "
                            "SELECT id FROM knowledge_document_chunks "
                            "ORDER BY embedding <=> CAST(:query_vector AS vector) LIMIT 2"
                        ),
                        {"query_vector": vector_literal},
                    )
                ).scalars()
            )
            assert "knowledge_document_chunks_embedding_hnsw_idx" in hnsw_plan
    finally:
        await _cleanup(factory, [target, other_workspace])


@pytest.mark.anyio
async def test_owner_admin_member_allowed_outsider_and_cross_workspace_hidden(
    retrieval_factory,
) -> None:
    factory = retrieval_factory
    target = await _create_scope(factory, name="RBAC target")
    foreign = await _create_scope(factory, name="RBAC foreign")
    admin_id, member_id, outsider_id = uuid4(), uuid4(), uuid4()
    try:
        async with factory() as session, session.begin():
            session.add_all(
                [
                    User(id=admin_id, email=f"admin-{admin_id.hex}@example.invalid"),
                    User(id=member_id, email=f"member-{member_id.hex}@example.invalid"),
                    User(id=outsider_id, email=f"outsider-{outsider_id.hex}@example.invalid"),
                ]
            )
            await session.flush()
            await workspace_repo.create_membership(
                session,
                workspace_id=target.workspace_id,
                user_id=admin_id,
                role=WorkspaceRole.ADMIN,
            )
            await workspace_repo.create_membership(
                session,
                workspace_id=target.workspace_id,
                user_id=member_id,
                role=WorkspaceRole.MEMBER,
            )
            await _add_document_generation(
                session,
                scope=target,
                filename="rbac.txt",
                vector=_unit_vector(),
                content="rbac",
            )
        for actor_id in (target.owner_id, admin_id, member_id):
            provider = DeterministicQueryProvider(_unit_vector())
            result = await _service(factory, provider).search(
                target.workspace_id, target.knowledge_base_id, actor_id, "allowed", 5, None
            )
            assert result.total == 1 and provider.calls

        provider = DeterministicQueryProvider(_unit_vector())
        with pytest.raises(NotFoundError):
            await _service(factory, provider).search(
                target.workspace_id,
                target.knowledge_base_id,
                outsider_id,
                "hidden",
                5,
                None,
            )
        assert provider.calls == []

        provider = DeterministicQueryProvider(_unit_vector())
        with pytest.raises(NotFoundError):
            await _service(factory, provider).search(
                target.workspace_id,
                foreign.knowledge_base_id,
                target.owner_id,
                "cross workspace",
                5,
                None,
            )
        assert provider.calls == []
    finally:
        async with factory() as session, session.begin():
            for user_id in (admin_id, member_id, outsider_id):
                await session.execute(delete(User).where(User.id == user_id))
        await _cleanup(factory, [target, foreign])


@pytest.mark.anyio
async def test_active_generation_wins_during_failed_and_successful_reindex(
    retrieval_factory,
) -> None:
    factory = retrieval_factory
    scope = await _create_scope(factory, name="Generation")
    try:
        document_id = uuid4()
        async with factory() as session, session.begin():
            _, old_generation, old_chunk = await _add_document_generation(
                session,
                scope=scope,
                document_id=document_id,
                filename="generation.txt",
                vector=_unit_vector(),
                content="old active generation",
            )
            failed_generation = uuid4()
            session.add(
                KnowledgeIndexJob(
                    workspace_id=scope.workspace_id,
                    knowledge_base_id=scope.knowledge_base_id,
                    document_id=document_id,
                    index_generation_id=failed_generation,
                    status="failed",
                    embedding_model="newer-but-failed-model",
                    embedding_dimensions=DIMENSIONS,
                    chunking_config_version="character-v1:1000:150:2500",
                    content_sha256="0" * 64,
                    attempt_count=1,
                    claim_generation=1,
                    error_code="EMBEDDING_PROVIDER_UNAVAILABLE",
                )
            )
        first = await _service(factory, DeterministicQueryProvider(_unit_vector())).search(
            scope.workspace_id, scope.knowledge_base_id, scope.owner_id, "old", 5, None
        )
        assert [item.chunk_id for item in first.results] == [old_chunk]

        async with factory() as session, session.begin():
            _, new_generation, new_chunk = await _add_document_generation(
                session,
                scope=scope,
                document_id=document_id,
                filename="generation.txt",
                vector=_unit_vector(0.0, 1.0),
                content="new active generation",
            )
            assert new_generation != old_generation
        switched = await _service(factory, DeterministicQueryProvider(_unit_vector())).search(
            scope.workspace_id, scope.knowledge_base_id, scope.owner_id, "new", 5, None
        )
        assert [item.chunk_id for item in switched.results] == [new_chunk]
        assert old_chunk not in [item.chunk_id for item in switched.results]
    finally:
        await _cleanup(factory, [scope])


@pytest.mark.anyio
async def test_empty_deleted_and_incompatible_active_indexes_fail_closed(
    retrieval_factory,
) -> None:
    factory = retrieval_factory
    scope = await _create_scope(factory, name="Empty delete model")
    try:
        provider = DeterministicQueryProvider(_unit_vector())
        empty = await _service(factory, provider).search(
            scope.workspace_id, scope.knowledge_base_id, scope.owner_id, "empty", 5, None
        )
        assert empty.results == [] and provider.calls == []

        async with factory() as session, session.begin():
            document_id, _, _ = await _add_document_generation(
                session,
                scope=scope,
                filename="delete.txt",
                vector=_unit_vector(),
                content="delete me",
            )
        async with factory() as session, session.begin():
            document = await session.get(KnowledgeDocument, document_id)
            await session.delete(document)
        deleted = await _service(factory, DeterministicQueryProvider(_unit_vector())).search(
            scope.workspace_id, scope.knowledge_base_id, scope.owner_id, "deleted", 5, None
        )
        assert deleted.results == []

        async with factory() as session, session.begin():
            await _add_document_generation(
                session,
                scope=scope,
                filename="incompatible.txt",
                vector=_unit_vector(),
                content="incompatible",
                model="different-semantic-space",
            )
        provider = DeterministicQueryProvider(_unit_vector())
        with pytest.raises(ContentUnavailableError) as captured:
            await _service(factory, provider).search(
                scope.workspace_id,
                scope.knowledge_base_id,
                scope.owner_id,
                "must reject",
                5,
                None,
            )
        assert captured.value.code == "KNOWLEDGE_INDEX_MODEL_INCOMPATIBLE"
        assert provider.calls == []
    finally:
        await _cleanup(factory, [scope])
