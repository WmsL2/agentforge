"""Knowledge Agent HTTP authentication, validation, and response contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_knowledge_agent_service
from app.core.exceptions import ContentUnavailableError, NotFoundError
from app.main import app
from app.services.knowledge.agent_service import KnowledgeAgentResult, KnowledgeAgentSource


@pytest.mark.anyio
async def test_ask_returns_no_store_and_backend_sources() -> None:
    user = SimpleNamespace(id=uuid4())
    workspace_id, base_id = uuid4(), uuid4()
    result = KnowledgeAgentResult(
        answer="grounded answer",
        status="answered",
        sources=[
            KnowledgeAgentSource(
                chunk_id=uuid4(),
                document_id=uuid4(),
                filename="source.txt",
                page_start=1,
                page_end=1,
                similarity_score=0.9,
            )
        ],
    )
    service = SimpleNamespace(ask=AsyncMock(return_value=result))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_agent_service] = lambda: service
    url = f"/api/v1/workspaces/{workspace_id}/knowledge-bases/{base_id}/ask"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(url, json={"question": "question"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json()["sources"][0]["filename"] == "source.txt"
    service.ask.assert_awaited_once_with(workspace_id, base_id, user.id, "question")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [{}, {"question": ""}, {"question": "   "}, {"question": "q", "workspace_id": "forged"}],
)
async def test_ask_rejects_invalid_and_forged_scope_payload(payload) -> None:
    service = SimpleNamespace(ask=AsyncMock())
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
    app.dependency_overrides[get_knowledge_agent_service] = lambda: service
    url = f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/ask"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(url, json=payload)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    service.ask.assert_not_awaited()


@pytest.mark.anyio
async def test_ask_requires_authentication() -> None:
    url = f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/ask"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(url, json={"question": "q"})
    assert response.status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (NotFoundError(), 404, "NOT_FOUND"),
        (
            ContentUnavailableError(code="KNOWLEDGE_AGENT_DISABLED"),
            409,
            "KNOWLEDGE_AGENT_DISABLED",
        ),
    ],
)
async def test_ask_maps_scope_and_configuration_failures(error, status, code) -> None:
    service = SimpleNamespace(ask=AsyncMock(side_effect=error))
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
    app.dependency_overrides[get_knowledge_agent_service] = lambda: service
    url = f"/api/v1/workspaces/{uuid4()}/knowledge-bases/{uuid4()}/ask"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(url, json={"question": "q"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_ask_openapi_request_exposes_only_question() -> None:
    schema = app.openapi()
    path = "/api/v1/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/ask"
    request_ref = schema["paths"][path]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[-1]]
    assert set(request_schema["properties"]) == {"question"}
