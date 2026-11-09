"""Retrieval orchestration, validation, and safe failure tests."""

from contextlib import AbstractAsyncContextManager
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import (
    ContentUnavailableError,
    DatabaseError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from app.repositories.knowledge_retrieval import ActiveIndexProfile, KnowledgeRetrievalRow
from app.services.knowledge.embedding import EmbeddingError
from app.services.knowledge.retrieval_service import KnowledgeRetrievalService
from app.services.workspace.domain import WorkspacePermission


class _AsyncContext(AbstractAsyncContextManager):
    def __init__(self, value: object):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Session:
    def begin(self):
        return _AsyncContext(None)


class _SessionFactory:
    def __init__(self):
        self.sessions: list[_Session] = []

    def __call__(self):
        session = _Session()
        self.sessions.append(session)
        return _AsyncContext(session)


class _Provider:
    model = "text-embedding-3-small"
    dimensions = 1536

    def __init__(self, vectors: list[list[float]] | None = None, error: Exception | None = None):
        self.vectors = [[1.0] + [0.0] * 1535] if vectors is None else vectors
        self.error = error
        self.calls: list[list[str]] = []
        self.closed = False

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.error is not None:
            raise self.error
        return self.vectors

    async def aclose(self) -> None:
        self.closed = True


def _service(provider: _Provider):
    factory = _SessionFactory()
    service = KnowledgeRetrievalService(
        cast(Any, factory),
        lambda: provider,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        embedding_timeout_seconds=1,
        db_statement_timeout_ms=5000,
    )
    return service, factory


def _profile(model: str = "text-embedding-3-small", dimensions: int = 1536):
    return [ActiveIndexProfile(model, dimensions, 1)]


def _row():
    return KnowledgeRetrievalRow(
        chunk_id=uuid4(),
        document_id=uuid4(),
        knowledge_base_id=uuid4(),
        filename="source.txt",
        chunk_index=0,
        content="matched content",
        start_offset=0,
        end_offset=15,
        page_start=None,
        page_end=None,
        similarity_score=0.75,
    )


@pytest.mark.anyio
async def test_authorization_and_model_preflight_precede_embedding_and_use_fresh_session() -> None:
    provider = _Provider()
    service, factory = _service(provider)
    workspace_id, base_id, actor_id = uuid4(), uuid4(), uuid4()
    events: list[str] = []

    async def authorize(*args, **kwargs):
        events.append("authorize")

    async def profiles(*args, **kwargs):
        events.append("preflight")
        return _profile()

    async def search(*args, **kwargs):
        events.append("search")
        return [_row()]

    original_embed = provider.embed_documents

    async def embed(texts):
        events.append("embed")
        return await original_embed(texts)

    provider.embed_documents = embed
    with (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            side_effect=authorize,
        ) as require_permission,
        patch(
            "app.services.knowledge.retrieval_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.list_active_index_profiles",
            side_effect=profiles,
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.search_active_chunks",
            side_effect=search,
        ),
    ):
        result = await service.search(workspace_id, base_id, actor_id, "  中文问题  ", 5, None)

    assert events == ["authorize", "preflight", "embed", "search"]
    assert len(factory.sessions) == 2
    assert result.query == "中文问题" and result.total == 1
    assert provider.closed
    require_permission.assert_awaited_once_with(
        workspace_id, actor_id, WorkspacePermission.KNOWLEDGE_READ
    )


@pytest.mark.anyio
async def test_unauthorized_or_cross_workspace_resource_never_calls_provider() -> None:
    provider = _Provider()
    service, _ = _service(provider)
    with (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            AsyncMock(side_effect=NotFoundError(message="Workspace not found")),
        ),
        pytest.raises(NotFoundError),
    ):
        await service.search(uuid4(), uuid4(), uuid4(), "query", 5, None)
    assert provider.calls == []

    with (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            AsyncMock(),
        ),
        patch(
            "app.services.knowledge.retrieval_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=None),
        ),
        pytest.raises(NotFoundError, match="Knowledge base"),
    ):
        await service.search(uuid4(), uuid4(), uuid4(), "query", 5, None)
    assert provider.calls == []


@pytest.mark.anyio
async def test_empty_index_returns_empty_without_embedding() -> None:
    provider = _Provider()
    service, factory = _service(provider)
    with (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            AsyncMock(),
        ),
        patch(
            "app.services.knowledge.retrieval_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.list_active_index_profiles",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await service.search(uuid4(), uuid4(), uuid4(), "query", 5, None)
    assert result.results == [] and result.total == 0
    assert provider.calls == [] and len(factory.sessions) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("model", "dimensions"),
    [("different-model", 1536), ("text-embedding-3-small", 3072)],
)
async def test_incompatible_active_model_fails_before_embedding(model, dimensions) -> None:
    provider = _Provider()
    service, _ = _service(provider)
    with (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            AsyncMock(),
        ),
        patch(
            "app.services.knowledge.retrieval_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.list_active_index_profiles",
            AsyncMock(return_value=_profile(model, dimensions)),
        ),
        pytest.raises(ContentUnavailableError) as captured,
    ):
        await service.search(uuid4(), uuid4(), uuid4(), "query", 5, None)
    assert captured.value.code == "KNOWLEDGE_INDEX_MODEL_INCOMPATIBLE"
    assert provider.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("vectors", "code"),
    [
        ([], "EMBEDDING_COUNT_MISMATCH"),
        ([[1.0]], "EMBEDDING_DIMENSION_MISMATCH"),
        ([[float("nan")] + [0.0] * 1535], "EMBEDDING_VALUE_INVALID"),
        ([[float("inf")] + [0.0] * 1535], "EMBEDDING_VALUE_INVALID"),
        ([[0.0] * 1536], "EMBEDDING_ZERO_VECTOR"),
    ],
)
async def test_invalid_query_embeddings_are_safe_external_errors(vectors, code) -> None:
    provider = _Provider(vectors=vectors)
    service, _ = _service(provider)
    with (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            AsyncMock(),
        ),
        patch(
            "app.services.knowledge.retrieval_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.list_active_index_profiles",
            AsyncMock(return_value=_profile()),
        ),
        pytest.raises(ExternalServiceError) as captured,
    ):
        await service.search(uuid4(), uuid4(), uuid4(), "secret query", 5, None)
    assert captured.value.code == code
    assert "secret query" not in captured.value.message
    assert provider.closed


@pytest.mark.anyio
async def test_provider_and_database_failures_expose_only_stable_codes() -> None:
    provider = _Provider(error=EmbeddingError("EMBEDDING_RATE_LIMITED", retryable=True))
    service, _ = _service(provider)
    common = (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            AsyncMock(),
        ),
        patch(
            "app.services.knowledge.retrieval_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.list_active_index_profiles",
            AsyncMock(return_value=_profile()),
        ),
    )
    with common[0], common[1], common[2], pytest.raises(ExternalServiceError) as captured:
        await service.search(uuid4(), uuid4(), uuid4(), "query", 5, None)
    assert captured.value.code == "EMBEDDING_RATE_LIMITED"

    provider = _Provider()
    service, _ = _service(provider)
    with (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            AsyncMock(),
        ),
        patch(
            "app.services.knowledge.retrieval_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.list_active_index_profiles",
            AsyncMock(side_effect=SQLAlchemyError()),
        ),
        pytest.raises(DatabaseError) as captured,
    ):
        await service.search(uuid4(), uuid4(), uuid4(), "query", 5, None)
    assert captured.value.code == "KNOWLEDGE_RETRIEVAL_DATABASE_ERROR"


@pytest.mark.anyio
async def test_missing_api_key_and_vector_query_failure_are_safe() -> None:
    factory = _SessionFactory()
    service = KnowledgeRetrievalService(
        cast(Any, factory),
        lambda: (_ for _ in ()).throw(EmbeddingError("EMBEDDING_API_KEY_MISSING")),
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        embedding_timeout_seconds=1,
        db_statement_timeout_ms=5000,
    )
    with (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            AsyncMock(),
        ),
        patch(
            "app.services.knowledge.retrieval_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.list_active_index_profiles",
            AsyncMock(return_value=_profile()),
        ),
        pytest.raises(ExternalServiceError) as captured,
    ):
        await service.search(uuid4(), uuid4(), uuid4(), "query", 5, None)
    assert captured.value.code == "EMBEDDING_API_KEY_MISSING"

    provider = _Provider()
    service, _ = _service(provider)
    with (
        patch(
            "app.services.knowledge.retrieval_service.WorkspaceAuthorizationService.require_permission",
            AsyncMock(),
        ),
        patch(
            "app.services.knowledge.retrieval_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.list_active_index_profiles",
            AsyncMock(return_value=_profile()),
        ),
        patch(
            "app.services.knowledge.retrieval_service.retrieval_repo.search_active_chunks",
            AsyncMock(side_effect=SQLAlchemyError()),
        ),
        pytest.raises(DatabaseError) as captured,
    ):
        await service.search(uuid4(), uuid4(), uuid4(), "query", 5, None)
    assert captured.value.code == "KNOWLEDGE_RETRIEVAL_DATABASE_ERROR"


@pytest.mark.parametrize(
    ("query", "top_k", "min_score"),
    [
        (" ", 5, None),
        ("x" * 2001, 5, None),
        ("q", 0, None),
        ("q", 21, None),
        ("q", 5, -1.1),
        ("q", 5, 1.1),
    ],
)
@pytest.mark.anyio
async def test_defensive_service_input_validation(query, top_k, min_score) -> None:
    service, _ = _service(_Provider())
    with pytest.raises(ValidationError):
        await service.search(uuid4(), uuid4(), uuid4(), query, top_k, min_score)
