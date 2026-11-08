"""Authorized API service and background executor for knowledge indexing."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import ContentUnavailableError, NotFoundError
from app.repositories import knowledge as knowledge_repo
from app.repositories import knowledge_document as document_repo
from app.repositories import knowledge_index as index_repo
from app.services.knowledge.chunking import (
    ChunkingConfig,
    ChunkLimitExceededError,
    chunk_document,
)
from app.services.knowledge.embedding import EmbeddingError, EmbeddingProvider
from app.services.knowledge.embedding.provider import validate_embeddings
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspacePermission

logger = logging.getLogger(__name__)


class KnowledgeIndexDispatcher(Protocol):
    async def dispatch(self, job_id: UUID) -> None: ...


@dataclass(frozen=True)
class IndexExecutionResult:
    job_id: UUID
    status: str


class KnowledgeIndexingService:
    def __init__(
        self,
        db: AsyncSession,
        authorization: WorkspaceAuthorizationService,
        dispatcher: KnowledgeIndexDispatcher,
        *,
        chunking_config: ChunkingConfig,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> None:
        self._db = db
        self._authorization = authorization
        self._dispatcher = dispatcher
        self._chunking_config = chunking_config
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions

    async def request_index(
        self, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID, actor_user_id: UUID
    ):
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_EDIT
        )
        document = await self._require_document(workspace_id, knowledge_base_id, document_id)
        if document.parse_status != "ready" or document.parsed_content is None:
            raise ContentUnavailableError(
                message="Only successfully parsed documents can be indexed",
                code="DOCUMENT_NOT_READY_FOR_INDEXING",
            )
        job, created = await index_repo.create_pending_idempotent(
            self._db,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            embedding_model=self._embedding_model,
            embedding_dimensions=self._embedding_dimensions,
            chunking_config_version=self._chunking_config.version,
            content_sha256=hashlib.sha256(document.parsed_content.encode()).hexdigest(),
        )
        # Durability boundary: broker publication is strictly after the job commit.
        await self._db.commit()
        if created:
            try:
                await self._dispatcher.dispatch(job.id)
            except Exception:
                logger.warning(
                    "Knowledge index dispatch failed; recovery scan will retry",
                    extra={"knowledge_index_job_id": str(job.id)},
                )
        return job

    async def get_index_status(
        self, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID, actor_user_id: UUID
    ) -> dict[str, object]:
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_READ
        )
        document = await self._require_document(workspace_id, knowledge_base_id, document_id)
        job = await index_repo.get_latest_job_scoped(
            self._db,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
        active_job = await index_repo.get_job_by_generation(
            self._db,
            document_id=document_id,
            generation_id=document.active_index_generation_id,
        )
        effective_job = active_job or job
        return {
            "document_id": document.id,
            "job_id": None if job is None else job.id,
            "status": "not_indexed" if job is None else job.status,
            "active_generation_id": document.active_index_generation_id,
            "chunk_count": await index_repo.count_active_chunks(self._db, document),
            "embedding_model": None if effective_job is None else effective_job.embedding_model,
            "index_version": (
                None if effective_job is None else effective_job.chunking_config_version
            ),
            "error_code": None if job is None else job.error_code,
        }

    async def _require_document(
        self, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ):
        knowledge_base = await knowledge_repo.get_by_workspace_and_id(
            self._db, workspace_id=workspace_id, knowledge_base_id=knowledge_base_id
        )
        if knowledge_base is None:
            raise NotFoundError(message="Knowledge base not found")
        document = await document_repo.get_scoped(
            self._db,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
        if document is None:
            raise NotFoundError(message="Knowledge document not found")
        return document


class KnowledgeIndexExecutor:
    """Claim briefly, embed with no DB connection, then commit one fenced generation."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider_factory: Callable[[], EmbeddingProvider],
        *,
        chunking_config: ChunkingConfig,
        lease_duration: timedelta,
    ) -> None:
        self._session_factory = session_factory
        self._provider_factory = provider_factory
        self._chunking_config = chunking_config
        self._lease_duration = lease_duration

    async def execute(self, job_id: UUID) -> IndexExecutionResult:
        async with self._session_factory() as db, db.begin():
            lease = await index_repo.claim_job(
                db, job_id=job_id, lease_duration=self._lease_duration
            )
        if lease is None:
            return IndexExecutionResult(job_id, "not_claimed")
        try:
            async with self._session_factory() as db, db.begin():
                source = await index_repo.load_claimed_source(db, lease)
            if source is None:
                return IndexExecutionResult(job_id, "lease_lost")
            job, document = source
            if document.parse_status != "ready" or document.parsed_content is None:
                raise EmbeddingError("DOCUMENT_NOT_READY_FOR_INDEXING")
            digest = hashlib.sha256(document.parsed_content.encode()).hexdigest()
            if digest != job.content_sha256:
                raise EmbeddingError("DOCUMENT_CONTENT_CHANGED")
            chunks = chunk_document(
                document.parsed_content, document.parse_metadata, self._chunking_config
            )
            if not chunks:
                raise EmbeddingError("DOCUMENT_HAS_NO_INDEXABLE_TEXT")
            provider = self._provider_factory()
            if (
                provider.model != job.embedding_model
                or provider.dimensions != job.embedding_dimensions
            ):
                raise EmbeddingError("EMBEDDING_CONFIGURATION_MISMATCH")
            vectors = validate_embeddings(
                await self._embed_with_heartbeat(
                    lease, provider, [chunk.content for chunk in chunks]
                ),
                expected_count=len(chunks),
                dimensions=job.embedding_dimensions,
            )
            async with self._session_factory() as db, db.begin():
                completed = await index_repo.complete_job(
                    db, lease=lease, chunks=chunks, vectors=vectors
                )
            return IndexExecutionResult(job_id, "succeeded" if completed else "lease_lost")
        except ChunkLimitExceededError:
            return await self._fail(lease, "DOCUMENT_CHUNK_LIMIT_EXCEEDED")
        except EmbeddingError as error:
            return await self._fail(lease, error.safe_code)
        except Exception:
            logger.exception(
                "Knowledge index execution failed",
                extra={"knowledge_index_job_id": str(job_id)},
            )
            return await self._fail(lease, "KNOWLEDGE_INDEX_INTERNAL_ERROR")

    async def _embed_with_heartbeat(
        self, lease: index_repo.IndexLease, provider: EmbeddingProvider, texts: list[str]
    ) -> list[list[float]]:
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat_lease(lease, stop))
        try:
            return await provider.embed_documents(texts)
        finally:
            stop.set()
            await heartbeat

    async def _heartbeat_lease(self, lease: index_repo.IndexLease, stop: asyncio.Event) -> None:
        interval = max(min(self._lease_duration.total_seconds() / 3, 60.0), 1.0)
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                async with self._session_factory() as db, db.begin():
                    renewed = await index_repo.renew_job(
                        db, lease=lease, lease_duration=self._lease_duration
                    )
            except Exception:
                logger.exception(
                    "Knowledge index lease heartbeat failed",
                    extra={"knowledge_index_job_id": str(lease.job_id)},
                )
                return
            if not renewed:
                return

    async def _fail(self, lease: index_repo.IndexLease, error_code: str) -> IndexExecutionResult:
        try:
            async with self._session_factory() as db, db.begin():
                failed = await index_repo.fail_job(db, lease=lease, error_code=error_code)
        except Exception:
            logger.exception(
                "Knowledge index failure state could not be persisted",
                extra={"knowledge_index_job_id": str(lease.job_id)},
            )
            raise
        return IndexExecutionResult(lease.job_id, "failed" if failed else "lease_lost")
