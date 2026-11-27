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


@pytest.fixture
def index_execution(monkeypatch):
    import hashlib
    from datetime import timedelta
    from unittest.mock import MagicMock

    from app.services.knowledge import indexing_service as module

    job_id = uuid4()
    db = MagicMock()
    db.__aenter__.return_value = db
    lease = SimpleNamespace(job_id=job_id)
    provider = SimpleNamespace(
        model="synthetic",
        dimensions=2,
        embed_documents=AsyncMock(return_value=[[1.0, 0.0]]),
        aclose=AsyncMock(),
    )
    factory = MagicMock(return_value=provider)
    document = SimpleNamespace(parse_status="ready", parsed_content="hello", parse_metadata={})
    job = SimpleNamespace(
        content_sha256=hashlib.sha256(b"hello").hexdigest(),
        embedding_model="synthetic",
        embedding_dimensions=2,
    )
    for name, result in [
        ("claim_job", lease),
        ("load_claimed_source", (job, document)),
        ("complete_job", True),
        ("fail_job", True),
    ]:
        monkeypatch.setattr(module.index_repo, name, AsyncMock(return_value=result))
    executor = module.KnowledgeIndexExecutor(
        lambda: db,
        factory,
        chunking_config=ChunkingConfig(),
        lease_duration=timedelta(seconds=3),
    )
    return SimpleNamespace(
        executor=executor, job_id=job_id, provider=provider, factory=factory, repo=module.index_repo
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "stage,expected",
    [
        ("success", "succeeded"),
        ("close_error", "succeeded"),
        ("mismatch", "failed"),
        ("embedding", "failed"),
        ("validation", "failed"),
        ("persistence", "failed"),
        ("lease_lost", "lease_lost"),
        ("no_claim", "not_claimed"),
        ("legacy", "succeeded"),
    ],
)
async def test_executor_closes_owned_provider_once(index_execution, stage, expected):
    case = index_execution
    close = case.provider.aclose
    if stage == "mismatch":
        case.provider.model = "different"
    elif stage == "embedding":
        case.provider.embed_documents.side_effect = RuntimeError("synthetic embedding error")
    elif stage == "validation":
        case.provider.embed_documents.return_value = []
    elif stage == "persistence":
        case.repo.complete_job.side_effect = RuntimeError("synthetic write error")
    elif stage == "lease_lost":
        case.repo.complete_job.return_value = False
    elif stage == "no_claim":
        case.repo.claim_job.return_value = None
    elif stage == "legacy":
        del case.provider.aclose
    elif stage == "close_error":
        close.side_effect = RuntimeError("synthetic close error")
    assert (await case.executor.execute(case.job_id)).status == expected
    if stage in {"legacy", "no_claim"}:
        close.assert_not_awaited()
    else:
        close.assert_awaited_once()
    if stage == "no_claim":
        case.factory.assert_not_called()
    if expected != "failed":
        case.repo.fail_job.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("cancel", [False, True])
async def test_heartbeat_renewal_is_joined_before_provider_close(
    index_execution, monkeypatch, cancel
):
    import asyncio

    from app.services.knowledge import indexing_service as module

    case = index_execution
    renewal_started = asyncio.Event()
    renewal_stopped = asyncio.Event()

    async def renew(*args, **kwargs):
        renewal_started.set()
        try:
            await asyncio.Future()
        finally:
            renewal_stopped.set()

    async def embed(_):
        await renewal_started.wait()
        if cancel:
            await asyncio.Future()
        return [[1.0, 0.0]]

    async def close():
        assert renewal_stopped.is_set()

    monkeypatch.setattr(case.repo, "renew_job", renew)
    monkeypatch.setattr(module, "_HEARTBEAT_STOP_GRACE_SECONDS", 0.01)
    case.provider.embed_documents.side_effect = embed
    case.provider.aclose.side_effect = close
    task = asyncio.create_task(case.executor.execute(case.job_id))
    try:
        async with asyncio.timeout(4):
            await renewal_started.wait()
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                case.repo.complete_job.assert_not_awaited()
            else:
                assert (await task).status == "succeeded"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert renewal_stopped.is_set()
    case.provider.aclose.assert_awaited_once()
    case.repo.fail_job.assert_not_awaited()


@pytest.mark.anyio
async def test_provider_close_timeout_cannot_reclassify_success(index_execution, monkeypatch):
    import asyncio

    from app.services.knowledge import indexing_service as module

    async def close():
        await asyncio.Future()

    monkeypatch.setattr(module, "_PROVIDER_CLOSE_TIMEOUT_SECONDS", 0.01)
    index_execution.provider.aclose.side_effect = close
    async with asyncio.timeout(1):
        result = await index_execution.executor.execute(index_execution.job_id)
    assert result.status == "succeeded"
    index_execution.provider.aclose.assert_awaited_once()
    index_execution.repo.fail_job.assert_not_awaited()
