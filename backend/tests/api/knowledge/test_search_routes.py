"""Knowledge search HTTP validation, security, and response contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_knowledge_retrieval_service
from app.core.exceptions import AuthorizationError, ExternalServiceError, NotFoundError
from app.main import app
from app.services.knowledge.retrieval_service import KnowledgeSearchItem, KnowledgeSearchResult


@pytest.mark.anyio
async def test_search_returns_source_grounded_results_without_sensitive_fields() -> None:
    user = SimpleNamespace(id=uuid4())
    workspace_id, base_id, document_id, chunk_id = uuid4(), uuid4(), uuid4(), uuid4()
    result = KnowledgeSearchResult(
        query="草鱼体重与体长的关系",
        results=[
            KnowledgeSearchItem(
                chunk_id=chunk_id,
                document_id=document_id,
                knowledge_base_id=base_id,
                filename="fish.pdf",
                chunk_index=2,
                content="匹配片段",
                start_offset=10,
                end_offset=14,
                page_start=3,
                page_end=3,
                similarity_score=0.875,
            )
        ],
        total=1,
        embedding_model="text-embedding-3-small",
    )
    service = SimpleNamespace(search=AsyncMock(return_value=result))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_retrieval_service] = lambda: service
    url = f"/api/v1/workspaces/{workspace_id}/knowledge-bases/{base_id}/search"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(url, json={"query": result.query})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"
    body = response.json()
    assert body["total"] == 1 and body["results"][0]["filename"] == "fish.pdf"
    assert "embedding" not in body["results"][0]
    assert "storage_path" not in body["results"][0]
    service.search.assert_awaited_once_with(workspace_id, base_id, user.id, result.query, 5, None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 2001},
        {"query": "q", "top_k": 0},
        {"query": "q", "top_k": 21},
        {"query": "q", "min_score": -1.01},
        {"query": "q", "min_score": 1.01},
        {"query": "q", "embedding": [1.0]},
    ],
)
async def test_search_schema_rejects_invalid_or_client_vector_payload(payload) -> None:
    user = SimpleNamespace(id=uuid4())
    service = SimpleNamespace(search=AsyncMock())
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_retrieval_service] = lambda: service
    url = f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/search"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(url, json=payload)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    service.search.assert_not_awaited()


@pytest.mark.anyio
async def test_search_requires_authentication() -> None:
    url = f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/search"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(url, json={"query": "q"})
    assert response.status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (NotFoundError(), 404, "NOT_FOUND"),
        (AuthorizationError(), 403, "AUTHORIZATION_ERROR"),
        (
            ExternalServiceError(code="EMBEDDING_PROVIDER_UNAVAILABLE"),
            503,
            "EMBEDDING_PROVIDER_UNAVAILABLE",
        ),
    ],
)
async def test_search_maps_scoped_and_provider_failures(error, status, code) -> None:
    service = SimpleNamespace(search=AsyncMock(side_effect=error))
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
    app.dependency_overrides[get_knowledge_retrieval_service] = lambda: service
    url = f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/search"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(url, json={"query": "q"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_search_openapi_contract_has_no_client_embedding_field() -> None:
    schema = app.openapi()
    path = "/api/v1/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/search"
    operation = schema["paths"][path]["post"]
    request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[-1]]
    assert set(request_schema["properties"]) == {"query", "top_k", "min_score"}
