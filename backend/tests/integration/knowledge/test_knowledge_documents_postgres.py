"""Opt-in real PostgreSQL and HTTP proofs for Atomic 2 documents."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import Headers

from app.api.deps import get_current_user, get_knowledge_document_service
from app.db.models.knowledge import KnowledgeDocument
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.main import app
from app.repositories import knowledge as knowledge_repo
from app.repositories import workspace as workspace_repo
from app.services.knowledge.document_parser import KnowledgeDocumentParser
from app.services.knowledge.document_service import KnowledgeDocumentService
from app.services.knowledge.document_storage import KnowledgeDocumentStorage
from app.services.workspace import WorkspaceAuthorizationService, WorkspaceRole


async def _seed(session):
    user_id = uuid4()
    session.add(
        User(id=user_id, email=f"document-{user_id.hex}@example.invalid", hashed_password=None)
    )
    await session.flush()
    workspace = await workspace_repo.create_workspace(
        session, name=f"Documents {user_id.hex}", created_by_user_id=user_id
    )
    await workspace_repo.create_membership(
        session, workspace_id=workspace.id, user_id=user_id, role=WorkspaceRole.OWNER
    )
    base = await knowledge_repo.create(
        session,
        workspace_id=workspace.id,
        name="Documents",
        description=None,
        created_by_user_id=user_id,
    )
    other = await knowledge_repo.create(
        session,
        workspace_id=workspace.id,
        name="Other",
        description=None,
        created_by_user_id=user_id,
    )
    return user_id, workspace, base, other


@pytest.mark.anyio
async def test_real_postgres_http_upload_read_download_and_delete(
    postgres_session, tmp_path: Path
) -> None:
    user_id, workspace, base, other = await _seed(postgres_session)
    service = KnowledgeDocumentService(
        postgres_session,
        WorkspaceAuthorizationService(postgres_session),
        KnowledgeDocumentStorage(tmp_path),
        KnowledgeDocumentParser(),
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[get_knowledge_document_service] = lambda: service
    root = f"/api/v1/workspaces/{workspace.id}/knowledge-bases/{base.id}/documents"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                root, files={"file": ("notes.txt", b"hello postgres", "text/plain")}
            )
            assert created.status_code == 201, created.text
            document_id = created.json()["id"]
            assert "storage_path" not in created.json()
            listed = await client.get(root)
            content = await client.get(f"{root}/{document_id}/content")
            download = await client.get(f"{root}/{document_id}/download")
            hidden = await client.get(
                f"/api/v1/workspaces/{workspace.id}/knowledge-bases/{other.id}/documents/{document_id}"
            )
            deleted = await client.delete(f"{root}/{document_id}")
        assert listed.json()["total"] == 1
        assert content.json() == {
            "document_id": document_id,
            "content": "hello postgres",
            "page_count": None,
            "parse_metadata": {"format": "txt"},
        }
        assert download.content == b"hello postgres"
        assert hidden.status_code == 404
        assert deleted.status_code == 204
        assert (
            await postgres_session.get(KnowledgeDocument, __import__("uuid").UUID(document_id))
            is None
        )
        assert not list((tmp_path / "knowledge").rglob("*.txt"))
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_real_postgres_persists_legitimate_parse_failure(
    postgres_session, tmp_path: Path
) -> None:
    user_id, workspace, base, _ = await _seed(postgres_session)
    service = KnowledgeDocumentService(
        postgres_session,
        WorkspaceAuthorizationService(postgres_session),
        KnowledgeDocumentStorage(tmp_path),
        KnowledgeDocumentParser(),
    )
    row = await service.upload_document(
        workspace.id,
        base.id,
        user_id,
        UploadFile(
            file=BytesIO(b"\xff"),
            filename="bad.txt",
            headers=Headers({"content-type": "text/plain"}),
        ),
    )
    assert (row.parse_status, row.parse_error_code, row.parsed_content) == (
        "failed",
        "TEXT_NOT_UTF8",
        None,
    )
    assert (await postgres_session.get(KnowledgeDocument, row.id)).parse_status == "failed"


@pytest.mark.anyio
async def test_postgres_rejects_cross_workspace_pair_and_cascades(postgres_session) -> None:
    user_id, workspace, base, other = await _seed(postgres_session)
    second = await workspace_repo.create_workspace(
        postgres_session, name="Second", created_by_user_id=user_id
    )
    bad = KnowledgeDocument(
        workspace_id=second.id,
        knowledge_base_id=base.id,
        created_by_user_id=user_id,
        filename="x.txt",
        mime_type="text/plain",
        size_bytes=1,
        sha256="a" * 64,
        storage_path=f"{second.id}/{base.id}/{uuid4()}/x.txt",
        parse_status="ready",
        parse_error_code=None,
        parsed_content="x",
        page_count=None,
        parse_metadata={},
    )
    savepoint = await postgres_session.begin_nested()
    postgres_session.add(bad)
    with pytest.raises(IntegrityError):
        await postgres_session.flush()
    await savepoint.rollback()

    good = KnowledgeDocument(
        workspace_id=workspace.id,
        knowledge_base_id=base.id,
        created_by_user_id=user_id,
        filename="x.txt",
        mime_type="text/plain",
        size_bytes=1,
        sha256="a" * 64,
        storage_path=f"{workspace.id}/{base.id}/{uuid4()}/x.txt",
        parse_status="ready",
        parse_error_code=None,
        parsed_content="x",
        page_count=None,
        parse_metadata={},
    )
    postgres_session.add(good)
    await postgres_session.flush()
    document_id = good.id
    workspace_id = workspace.id
    other_id = other.id

    invalid = KnowledgeDocument(
        workspace_id=workspace.id,
        knowledge_base_id=base.id,
        created_by_user_id=user_id,
        filename="bad.txt",
        mime_type="text/plain",
        size_bytes=1,
        sha256="b" * 64,
        storage_path=f"{workspace.id}/{base.id}/{uuid4()}/bad.txt",
        parse_status="pending",
        parse_error_code=None,
        parsed_content=None,
        page_count=None,
        parse_metadata={},
    )
    savepoint = await postgres_session.begin_nested()
    postgres_session.add(invalid)
    with pytest.raises(IntegrityError):
        await postgres_session.flush()
    await savepoint.rollback()

    creator = await postgres_session.get(User, user_id)
    await postgres_session.delete(creator)
    await postgres_session.flush()
    postgres_session.expire_all()
    assert (await postgres_session.get(KnowledgeDocument, document_id)).created_by_user_id is None

    await postgres_session.delete(base)
    await postgres_session.flush()
    postgres_session.expire_all()
    assert await postgres_session.get(KnowledgeDocument, document_id) is None

    workspace_document = KnowledgeDocument(
        workspace_id=workspace_id,
        knowledge_base_id=other_id,
        created_by_user_id=None,
        filename="workspace.txt",
        mime_type="text/plain",
        size_bytes=1,
        sha256="c" * 64,
        storage_path=f"{workspace_id}/{other_id}/{uuid4()}/workspace.txt",
        parse_status="ready",
        parse_error_code=None,
        parsed_content="x",
        page_count=None,
        parse_metadata={},
    )
    postgres_session.add(workspace_document)
    await postgres_session.flush()
    workspace_document_id = workspace_document.id
    persisted_workspace = await postgres_session.get(Workspace, workspace_id)
    await postgres_session.delete(persisted_workspace)
    await postgres_session.flush()
    postgres_session.expire_all()
    assert await postgres_session.get(KnowledgeDocument, workspace_document_id) is None


@pytest.mark.anyio
async def test_reconciliation_recovers_database_cascade_orphans(
    postgres_session, tmp_path: Path
) -> None:
    user_id, workspace, base, _ = await _seed(postgres_session)
    storage = KnowledgeDocumentStorage(tmp_path)
    service = KnowledgeDocumentService(
        postgres_session,
        WorkspaceAuthorizationService(postgres_session),
        storage,
        KnowledgeDocumentParser(),
    )
    orphan = storage.build_storage_path(
        workspace_id=workspace.id,
        knowledge_base_id=base.id,
        document_id=uuid4(),
        filename="orphan.txt",
    )
    await storage.save(orphan, b"orphan")
    assert await service.reconcile_orphans() == 1
    assert not list((tmp_path / "knowledge").rglob("*.txt"))


@pytest.mark.anyio
async def test_committed_parsed_text_is_visible_in_independent_session(
    postgres_restart_session_factory, tmp_path: Path
) -> None:
    factory = postgres_restart_session_factory
    user_id: UUID | None = None
    workspace_id: UUID | None = None
    try:
        async with factory() as session:
            user_id, workspace, base, _ = await _seed(session)
            workspace_id = workspace.id
            service = KnowledgeDocumentService(
                session,
                WorkspaceAuthorizationService(session),
                KnowledgeDocumentStorage(tmp_path),
                KnowledgeDocumentParser(),
            )
            row = await service.upload_document(
                workspace.id,
                base.id,
                user_id,
                UploadFile(
                    file=BytesIO("跨会话文本".encode()),
                    filename="durable.txt",
                    headers=Headers({"content-type": "text/plain"}),
                ),
            )
            document_id = row.id

        async with factory() as session:
            durable = await session.get(KnowledgeDocument, document_id)
            assert durable is not None
            assert (durable.parse_status, durable.parsed_content) == ("ready", "跨会话文本")
    finally:
        if workspace_id is not None and user_id is not None:
            async with factory() as session:
                await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
