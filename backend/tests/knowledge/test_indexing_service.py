"""API job durability and recovery publication tests without external services."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ContentUnavailableError
from app.services.knowledge.chunking import ChunkingConfig
from app.services.knowledge.indexing_service import KnowledgeIndexingService
from app.services.workspace.domain import WorkspacePermission


def _service(*, dispatch_error: Exception | None = None):
    db = AsyncMock()
    authorization = AsyncMock()
    dispatcher = SimpleNamespace(dispatch=AsyncMock(side_effect=dispatch_error))
    service = KnowledgeIndexingService(
        db,
        authorization,
        dispatcher,
        chunking_config=ChunkingConfig(),
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
    )
    return service, db, authorization, dispatcher


@pytest.mark.anyio
async def test_job_commits_before_dispatch_and_broker_failure_keeps_job() -> None:
    service, db, authorization, dispatcher = _service(dispatch_error=RuntimeError("offline"))
    workspace_id, base_id, document_id, actor_id = uuid4(), uuid4(), uuid4(), uuid4()
    document = SimpleNamespace(
        id=document_id, parse_status="ready", parsed_content="hello", parse_metadata={}
    )
    job = SimpleNamespace(id=uuid4())
    events: list[str] = []
    db.commit.side_effect = lambda: events.append("commit")
    dispatcher.dispatch.side_effect = lambda _: (
        events.append("dispatch") or (_ for _ in ()).throw(RuntimeError("offline"))
    )
    with (
        patch(
            "app.services.knowledge.indexing_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.indexing_service.document_repo.get_scoped",
            AsyncMock(return_value=document),
        ),
        patch(
            "app.services.knowledge.indexing_service.index_repo.create_pending_idempotent",
            AsyncMock(return_value=(job, True)),
        ),
    ):
        assert await service.request_index(workspace_id, base_id, document_id, actor_id) is job
    authorization.require_permission.assert_awaited_once_with(
        workspace_id, actor_id, WorkspacePermission.KNOWLEDGE_EDIT
    )
    assert events == ["commit", "dispatch"]


@pytest.mark.anyio
async def test_active_request_is_idempotent_and_not_redispatched() -> None:
    service, db, _, dispatcher = _service()
    document = SimpleNamespace(parse_status="ready", parsed_content="hello")
    job = SimpleNamespace(id=uuid4())
    with (
        patch(
            "app.services.knowledge.indexing_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.indexing_service.document_repo.get_scoped",
            AsyncMock(return_value=document),
        ),
        patch(
            "app.services.knowledge.indexing_service.index_repo.create_pending_idempotent",
            AsyncMock(return_value=(job, False)),
        ),
    ):
        assert await service.request_index(uuid4(), uuid4(), uuid4(), uuid4()) is job
    db.commit.assert_awaited_once()
    dispatcher.dispatch.assert_not_awaited()


@pytest.mark.anyio
async def test_failed_document_is_rejected_before_job_creation() -> None:
    service, db, _, _ = _service()
    with (
        patch(
            "app.services.knowledge.indexing_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.indexing_service.document_repo.get_scoped",
            AsyncMock(return_value=SimpleNamespace(parse_status="failed", parsed_content=None)),
        ),
        patch(
            "app.services.knowledge.indexing_service.index_repo.create_pending_idempotent",
            AsyncMock(),
        ) as create,
        pytest.raises(ContentUnavailableError, match="successfully parsed"),
    ):
        await service.request_index(uuid4(), uuid4(), uuid4(), uuid4())
    create.assert_not_awaited()
    db.commit.assert_not_awaited()
