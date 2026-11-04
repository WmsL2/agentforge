"""HTTP contract tests for knowledge documents."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_knowledge_document_service
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ContentUnavailableError,
    NotFoundError,
)
from app.main import app


def _row(workspace_id, base_id):
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace_id,
        knowledge_base_id=base_id,
        created_by_user_id=uuid4(),
        filename="notes.txt",
        mime_type="text/plain",
        size_bytes=5,
        sha256="a" * 64,
        parse_status="ready",
        parse_error_code=None,
        page_count=None,
        parse_metadata={},
        created_at=datetime.now(UTC),
        updated_at=None,
    )


@pytest.mark.anyio
async def test_all_six_routes_forward_scope_and_hide_storage_path(tmp_path: Path) -> None:
    user = SimpleNamespace(id=uuid4())
    workspace_id, base_id = uuid4(), uuid4()
    row = _row(workspace_id, base_id)
    source = tmp_path / "notes.txt"
    source.write_bytes(b"hello")
    service = SimpleNamespace(
        upload_document=AsyncMock(return_value=row),
        list_documents=AsyncMock(return_value=([row], 1)),
        get_document=AsyncMock(return_value=row),
        get_content=AsyncMock(
            return_value=SimpleNamespace(parsed_content="hello", page_count=None, parse_metadata={})
        ),
        get_download=AsyncMock(return_value=(row, source)),
        delete_document=AsyncMock(),
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_document_service] = lambda: service
    base = f"/api/v1/workspaces/{workspace_id}/knowledge-bases/{base_id}/documents"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(base, files={"file": ("notes.txt", b"hello", "text/plain")})
            listed = await client.get(base)
            fetched = await client.get(f"{base}/{row.id}")
            content = await client.get(f"{base}/{row.id}/content")
            downloaded = await client.get(f"{base}/{row.id}/download")
            deleted = await client.delete(f"{base}/{row.id}")
    finally:
        app.dependency_overrides.clear()
    assert [
        created.status_code,
        listed.status_code,
        fetched.status_code,
        content.status_code,
        downloaded.status_code,
        deleted.status_code,
    ] == [201, 200, 200, 200, 200, 204]
    assert "storage_path" not in created.json()
    assert content.json() == {
        "document_id": str(row.id),
        "content": "hello",
        "page_count": None,
        "parse_metadata": {},
    }
    assert downloaded.content == b"hello"
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in downloaded.headers["content-disposition"]
    service.upload_document.assert_awaited_once_with(workspace_id, base_id, user.id, ANY)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status"),
    [(NotFoundError(message="hidden"), 404), (ContentUnavailableError(), 409)],
)
async def test_isolation_and_failed_content_errors_keep_status(error, status) -> None:
    user = SimpleNamespace(id=uuid4())
    service = SimpleNamespace(get_content=AsyncMock(side_effect=error))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_document_service] = lambda: service
    url = f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/documents/{uuid4()}/content"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(url)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status


@pytest.mark.anyio
async def test_unauthenticated_upload_is_401_before_service() -> None:
    service = SimpleNamespace(upload_document=AsyncMock())
    app.dependency_overrides[get_knowledge_document_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/documents",
                files={"file": ("a.txt", b"a", "text/plain")},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401
    service.upload_document.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AuthorizationError(message="edit required"), 403, "AUTHORIZATION_ERROR"),
        (
            BadRequestError(message="too large", code="DOCUMENT_TOO_LARGE"),
            400,
            "DOCUMENT_TOO_LARGE",
        ),
        (
            BadRequestError(message="unsupported", code="DOCUMENT_TYPE_UNSUPPORTED"),
            400,
            "DOCUMENT_TYPE_UNSUPPORTED",
        ),
    ],
)
async def test_upload_security_errors_are_mapped_without_success(error, status, code) -> None:
    user = SimpleNamespace(id=uuid4())
    service = SimpleNamespace(upload_document=AsyncMock(side_effect=error))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_document_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/documents",
                files={"file": ("a.txt", b"a", "text/plain")},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.anyio
async def test_upload_returns_persisted_failed_parse_status() -> None:
    user = SimpleNamespace(id=uuid4())
    workspace_id, base_id = uuid4(), uuid4()
    row = _row(workspace_id, base_id)
    row.parse_status = "failed"
    row.parse_error_code = "PDF_ENCRYPTED"
    service = SimpleNamespace(upload_document=AsyncMock(return_value=row))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_document_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workspaces/{workspace_id}/knowledge-bases/{base_id}/documents",
                files={"file": ("a.pdf", b"%PDF", "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201
    assert (response.json()["parse_status"], response.json()["parse_error_code"]) == (
        "failed",
        "PDF_ENCRYPTED",
    )
