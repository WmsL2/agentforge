"""Index API response and scoped forwarding contracts."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_knowledge_indexing_service
from app.core.exceptions import AuthorizationError, ContentUnavailableError, NotFoundError
from app.main import app


@pytest.mark.anyio
async def test_index_post_is_202_and_get_exposes_no_vector() -> None:
    user = SimpleNamespace(id=uuid4())
    workspace_id, base_id, document_id, job_id, generation_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    job = SimpleNamespace(
        id=job_id,
        document_id=document_id,
        status="pending",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        index_generation_id=generation_id,
        chunking_config_version="character-v1:1000:150:2500",
        attempt_count=0,
        error_code=None,
        created_at=datetime.now(UTC),
    )
    status = {
        "document_id": document_id,
        "job_id": job_id,
        "status": "succeeded",
        "active_generation_id": generation_id,
        "chunk_count": 2,
        "embedding_model": "text-embedding-3-small",
        "index_version": "character-v1:1000:150:2500",
        "error_code": None,
    }
    service = SimpleNamespace(
        request_index=AsyncMock(return_value=job),
        get_index_status=AsyncMock(return_value=status),
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_indexing_service] = lambda: service
    url = (
        f"/api/v1/workspaces/{workspace_id}/knowledge-bases/{base_id}/documents/{document_id}/index"
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(url)
            fetched = await client.get(url)
    finally:
        app.dependency_overrides.clear()
    assert created.status_code == 202
    assert fetched.status_code == 200
    assert fetched.json()["chunk_count"] == 2
    assert "embedding" not in fetched.json()
    service.request_index.assert_awaited_once_with(workspace_id, base_id, document_id, user.id)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "error", "status"),
    [
        ("post", AuthorizationError(), 403),
        ("post", ContentUnavailableError(code="DOCUMENT_NOT_READY_FOR_INDEXING"), 409),
        ("get", NotFoundError(), 404),
    ],
)
async def test_index_security_and_document_state_errors(method, error, status) -> None:
    user = SimpleNamespace(id=uuid4())
    service = SimpleNamespace(
        request_index=AsyncMock(side_effect=error),
        get_index_status=AsyncMock(side_effect=error),
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_indexing_service] = lambda: service
    url = f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/documents/{uuid4()}/index"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await getattr(client, method)(url)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status
