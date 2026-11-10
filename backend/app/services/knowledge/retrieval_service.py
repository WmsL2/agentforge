"""Authorized semantic retrieval with short database session lifetimes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import (
    ContentUnavailableError,
    DatabaseError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from app.repositories import knowledge as knowledge_repo
from app.repositories import knowledge_retrieval as retrieval_repo
from app.services.knowledge.embedding import EmbeddingError, EmbeddingProvider
from app.services.knowledge.embedding.provider import validate_embeddings
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspacePermission

logger = logging.getLogger(__name__)


@runtime_checkable
class AsyncClosableEmbeddingProvider(Protocol):
    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class KnowledgeSearchItem:
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


@dataclass(frozen=True)
class KnowledgeSearchResult:
    query: str
    results: list[KnowledgeSearchItem]
    total: int
    embedding_model: str


class KnowledgeRetrievalService:
    """Validate scope before embedding, then search through a fresh DB session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider_factory: Callable[[], EmbeddingProvider],
        *,
        embedding_model: str,
        embedding_dimensions: int,
        embedding_timeout_seconds: float,
        db_statement_timeout_ms: int,
    ) -> None:
        self._session_factory = session_factory
        self._provider_factory = provider_factory
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._embedding_timeout_seconds = embedding_timeout_seconds
        self._db_statement_timeout_ms = db_statement_timeout_ms

    async def search(
        self,
        workspace_id: UUID,
        knowledge_base_id: UUID,
        actor_user_id: UUID,
        query: str,
        top_k: int,
        min_score: float | None,
    ) -> KnowledgeSearchResult:
        normalized_query = query.strip()
        self._validate_input(normalized_query, top_k, min_score)

        try:
            async with self._session_factory() as db, db.begin():
                authorization = WorkspaceAuthorizationService(db)
                await authorization.require_permission(
                    workspace_id,
                    actor_user_id,
                    WorkspacePermission.KNOWLEDGE_READ,
                )
                knowledge_base = await knowledge_repo.get_by_workspace_and_id(
                    db,
                    workspace_id=workspace_id,
                    knowledge_base_id=knowledge_base_id,
                )
                if knowledge_base is None:
                    raise NotFoundError(message="Knowledge base not found")
                profiles = await retrieval_repo.list_active_index_profiles(
                    db,
                    workspace_id=workspace_id,
                    knowledge_base_id=knowledge_base_id,
                    statement_timeout_ms=self._db_statement_timeout_ms,
                )
        except SQLAlchemyError:
            logger.warning("Knowledge retrieval preflight database query failed")
            raise DatabaseError(
                message="Knowledge retrieval database query failed",
                code="KNOWLEDGE_RETRIEVAL_DATABASE_ERROR",
            ) from None

        if not profiles:
            return KnowledgeSearchResult(normalized_query, [], 0, self._embedding_model)
        incompatible = [
            profile
            for profile in profiles
            if profile.embedding_model != self._embedding_model
            or profile.embedding_dimensions != self._embedding_dimensions
        ]
        if incompatible:
            raise ContentUnavailableError(
                message="Active knowledge indexes use an incompatible embedding model",
                code="KNOWLEDGE_INDEX_MODEL_INCOMPATIBLE",
            )

        query_vector = await self._embed_query(normalized_query)
        try:
            async with self._session_factory() as db, db.begin():
                rows = await retrieval_repo.search_active_chunks(
                    db,
                    workspace_id=workspace_id,
                    knowledge_base_id=knowledge_base_id,
                    query_vector=query_vector,
                    embedding_model=self._embedding_model,
                    embedding_dimensions=self._embedding_dimensions,
                    top_k=top_k,
                    min_score=min_score,
                    statement_timeout_ms=self._db_statement_timeout_ms,
                )
        except SQLAlchemyError:
            logger.warning("Knowledge retrieval vector database query failed")
            raise DatabaseError(
                message="Knowledge retrieval database query failed",
                code="KNOWLEDGE_RETRIEVAL_DATABASE_ERROR",
            ) from None

        items = [KnowledgeSearchItem(**row.__dict__) for row in rows]
        return KnowledgeSearchResult(
            query=normalized_query,
            results=items,
            total=len(items),
            embedding_model=self._embedding_model,
        )

    async def authorize_scope(
        self,
        workspace_id: UUID,
        knowledge_base_id: UUID,
        actor_user_id: UUID,
    ) -> None:
        """Authorize a knowledge scope without embedding or holding a session open."""
        try:
            async with self._session_factory() as db, db.begin():
                authorization = WorkspaceAuthorizationService(db)
                await authorization.require_permission(
                    workspace_id,
                    actor_user_id,
                    WorkspacePermission.KNOWLEDGE_READ,
                )
                knowledge_base = await knowledge_repo.get_by_workspace_and_id(
                    db,
                    workspace_id=workspace_id,
                    knowledge_base_id=knowledge_base_id,
                )
                if knowledge_base is None:
                    raise NotFoundError(message="Knowledge base not found")
        except SQLAlchemyError:
            logger.warning("Knowledge agent scope authorization database query failed")
            raise DatabaseError(
                message="Knowledge retrieval database query failed",
                code="KNOWLEDGE_RETRIEVAL_DATABASE_ERROR",
            ) from None

    async def _embed_query(self, query: str) -> list[float]:
        provider: EmbeddingProvider | None = None
        try:
            provider = self._provider_factory()
            if (
                provider.model != self._embedding_model
                or provider.dimensions != self._embedding_dimensions
            ):
                raise EmbeddingError("EMBEDDING_CONFIGURATION_MISMATCH")
            async with asyncio.timeout(self._embedding_timeout_seconds):
                vectors = await provider.embed_documents([query])
            return validate_embeddings(
                vectors,
                expected_count=1,
                dimensions=self._embedding_dimensions,
            )[0]
        except TimeoutError:
            raise ExternalServiceError(
                message="Embedding service timed out",
                code="EMBEDDING_TIMEOUT",
            ) from None
        except EmbeddingError as error:
            raise ExternalServiceError(
                message="Embedding service unavailable",
                code=error.safe_code,
            ) from None
        except Exception:
            logger.warning("Knowledge query embedding failed")
            raise ExternalServiceError(
                message="Embedding service unavailable",
                code="EMBEDDING_PROVIDER_UNAVAILABLE",
            ) from None
        finally:
            if isinstance(provider, AsyncClosableEmbeddingProvider):
                try:
                    await provider.aclose()
                except Exception:
                    logger.warning("Embedding provider client close failed")

    @staticmethod
    def _validate_input(query: str, top_k: int, min_score: float | None) -> None:
        if not query or len(query) > 2000:
            raise ValidationError(
                message="Query must contain between 1 and 2000 characters",
                code="KNOWLEDGE_SEARCH_QUERY_INVALID",
            )
        if not 1 <= top_k <= 20:
            raise ValidationError(
                message="top_k must be between 1 and 20",
                code="KNOWLEDGE_SEARCH_TOP_K_INVALID",
            )
        if min_score is not None and not -1.0 <= min_score <= 1.0:
            raise ValidationError(
                message="min_score must be between -1 and 1",
                code="KNOWLEDGE_SEARCH_MIN_SCORE_INVALID",
            )
