"""Service transaction, permission, and isolation tests."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import UploadFile

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ContentUnavailableError,
    NotFoundError,
)
from app.services.knowledge.document_parser import ParsedDocument
from app.services.knowledge.document_service import MAX_DOCUMENT_BYTES, KnowledgeDocumentService
from app.services.workspace.domain import WorkspacePermission


def _service():
    db, auth, storage, parser = AsyncMock(), AsyncMock(), MagicMock(), MagicMock()
    storage.save = AsyncMock()
    storage.delete = AsyncMock()
    storage.resolve_for_download = AsyncMock()
    storage.reconcile_orphans = AsyncMock()
    storage.sanitize_filename.return_value = "a.txt"
    storage.build_storage_path.return_value = "w/k/d/a.txt"
    parser.parse.return_value = ParsedDocument("ready", "hello", None, None, {})
    return KnowledgeDocumentService(db, auth, storage, parser), db, auth, storage


@pytest.mark.anyio
async def test_upload_uses_edit_permission_commits_and_never_overreads() -> None:
    service, db, auth, storage = _service()
    workspace_id, base_id, actor_id = uuid4(), uuid4(), uuid4()
    upload = UploadFile(
        filename="a.txt",
        file=__import__("io").BytesIO(b"hello"),
        headers={"content-type": "text/plain"},
    )
    row = SimpleNamespace(id=uuid4())
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.create",
            AsyncMock(return_value=row),
        ) as create,
    ):
        assert await service.upload_document(workspace_id, base_id, actor_id, upload) is row
    auth.require_permission.assert_awaited_once_with(
        workspace_id, actor_id, WorkspacePermission.KNOWLEDGE_EDIT
    )
    storage.save.assert_awaited_once()
    create.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_commit_failure_rolls_back_and_deletes_file() -> None:
    service, db, _, storage = _service()
    db.commit.side_effect = RuntimeError("commit failed")
    upload = UploadFile(
        filename="a.txt",
        file=__import__("io").BytesIO(b"hello"),
        headers={"content-type": "text/plain"},
    )
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.create",
            AsyncMock(return_value=object()),
        ),
        pytest.raises(RuntimeError, match="commit failed"),
    ):
        await service.upload_document(uuid4(), uuid4(), uuid4(), upload)
    db.rollback.assert_awaited_once()
    storage.delete.assert_awaited_once_with("w/k/d/a.txt")


@pytest.mark.anyio
async def test_file_write_failure_creates_no_database_row() -> None:
    service, db, _, storage = _service()
    storage.save.side_effect = OSError("disk full")
    upload = UploadFile(
        filename="a.txt",
        file=__import__("io").BytesIO(b"hello"),
        headers={"content-type": "text/plain"},
    )
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.create", AsyncMock()
        ) as create,
        pytest.raises(OSError, match="disk full"),
    ):
        await service.upload_document(uuid4(), uuid4(), uuid4(), upload)
    create.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [RuntimeError("flush failed"), asyncio.CancelledError()])
async def test_database_write_failure_or_interruption_compensates_file(failure) -> None:
    service, db, _, storage = _service()
    upload = UploadFile(
        filename="a.txt",
        file=__import__("io").BytesIO(b"hello"),
        headers={"content-type": "text/plain"},
    )
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.create",
            AsyncMock(side_effect=failure),
        ),
        pytest.raises(type(failure)),
    ):
        await service.upload_document(uuid4(), uuid4(), uuid4(), upload)
    db.rollback.assert_awaited_once()
    storage.delete.assert_awaited_once_with("w/k/d/a.txt")


@pytest.mark.anyio
async def test_permission_denial_precedes_reads_and_writes() -> None:
    service, _, auth, storage = _service()
    auth.require_permission.side_effect = AuthorizationError(message="denied")
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(),
        ) as get_base,
        pytest.raises(AuthorizationError),
    ):
        await service.list_documents(uuid4(), uuid4(), uuid4(), skip=0, limit=10)
    get_base.assert_not_awaited()
    storage.save.assert_not_awaited()


@pytest.mark.anyio
async def test_cross_workspace_document_is_404() -> None:
    service, _, _, _ = _service()
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.get_scoped",
            AsyncMock(return_value=None),
        ),
        pytest.raises(NotFoundError),
    ):
        await service.get_document(uuid4(), uuid4(), uuid4(), uuid4())


@pytest.mark.anyio
async def test_failed_document_content_is_conflict() -> None:
    service, _, _, _ = _service()
    service.get_document = AsyncMock(
        return_value=SimpleNamespace(parse_status="failed", parsed_content=None)
    )
    with pytest.raises(ContentUnavailableError):
        await service.get_content(uuid4(), uuid4(), uuid4(), uuid4())


@pytest.mark.anyio
async def test_delete_commits_before_private_file_cleanup_and_tolerates_cleanup_failure() -> None:
    service, db, _, storage = _service()
    row = SimpleNamespace(storage_path="w/k/d/a.txt")
    storage.delete.side_effect = OSError("locked")
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.get_scoped",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.delete", AsyncMock()
        ) as delete,
    ):
        await service.delete_document(uuid4(), uuid4(), uuid4(), uuid4())
    delete.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_delete_commit_failure_keeps_file_for_retry() -> None:
    service, db, _, storage = _service()
    row = SimpleNamespace(storage_path="w/k/d/a.txt")
    db.commit.side_effect = RuntimeError("commit failed")
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.get_scoped",
            AsyncMock(return_value=row),
        ),
        patch("app.services.knowledge.document_service.document_repo.delete", AsyncMock()),
        pytest.raises(RuntimeError, match="commit failed"),
    ):
        await service.delete_document(uuid4(), uuid4(), uuid4(), uuid4())
    storage.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_parser_timeout_is_persisted_as_failed_and_slot_finishes() -> None:
    service, _, _, _ = _service()
    service._parser.parse.side_effect = lambda **_kwargs: (
        time.sleep(0.05) or ParsedDocument("ready", "late", None, None, {})
    )
    upload = UploadFile(
        filename="a.txt",
        file=__import__("io").BytesIO(b"hello"),
        headers={"content-type": "text/plain"},
    )
    with (
        patch("app.services.knowledge.document_service.PARSER_TIMEOUT_SECONDS", 0.001),
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.create",
            AsyncMock(return_value=object()),
        ) as create,
    ):
        await service.upload_document(uuid4(), uuid4(), uuid4(), upload)
    assert create.await_args.kwargs["parsed"].error_code == "DOCUMENT_PARSE_TIMEOUT"
    await asyncio.sleep(0.06)


@pytest.mark.anyio
async def test_oversized_upload_is_rejected_before_parse_or_storage() -> None:
    service, _, _, storage = _service()
    upload = UploadFile(
        filename="a.txt",
        file=__import__("io").BytesIO(b"x" * (MAX_DOCUMENT_BYTES + 1)),
        headers={"content-type": "text/plain"},
    )
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        pytest.raises(BadRequestError) as error,
    ):
        await service.upload_document(uuid4(), uuid4(), uuid4(), upload)
    assert error.value.code == "DOCUMENT_TOO_LARGE"
    service._parser.parse.assert_not_called()
    storage.save.assert_not_awaited()


@pytest.mark.anyio
async def test_duplicate_content_is_allowed_with_distinct_server_keys() -> None:
    service, db, _, storage = _service()
    storage.build_storage_path.side_effect = ["w/k/one/a.txt", "w/k/two/a.txt"]
    with (
        patch(
            "app.services.knowledge.document_service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=object()),
        ),
        patch(
            "app.services.knowledge.document_service.document_repo.create",
            AsyncMock(side_effect=[object(), object()]),
        ),
    ):
        for _ in range(2):
            await service.upload_document(
                uuid4(),
                uuid4(),
                uuid4(),
                UploadFile(
                    filename="a.txt",
                    file=__import__("io").BytesIO(b"same"),
                    headers={"content-type": "text/plain"},
                ),
            )
    assert [call.args[0] for call in storage.save.await_args_list] == [
        "w/k/one/a.txt",
        "w/k/two/a.txt",
    ]
    assert db.commit.await_count == 2
