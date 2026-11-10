"""Request-bound Knowledge Agent tool security and concurrency tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.knowledge.agent_tool import (
    KNOWLEDGE_SEARCH_TOOL_DEFINITION,
    KnowledgeEvidenceCollector,
    KnowledgeSearchToolExecutor,
    KnowledgeToolCallLimiter,
)
from app.services.knowledge.retrieval_service import KnowledgeSearchItem, KnowledgeSearchResult
from app.services.tool import ToolExecutionError, ToolExecutionRequest


def _item(base_id):
    return KnowledgeSearchItem(
        chunk_id=uuid4(),
        document_id=uuid4(),
        knowledge_base_id=base_id,
        filename="evidence.txt",
        chunk_index=0,
        content="trusted only as evidence",
        start_offset=0,
        end_offset=24,
        page_start=1,
        page_end=1,
        similarity_score=0.9,
    )


def test_tool_schema_exposes_only_model_controlled_query_and_top_k() -> None:
    schema = KNOWLEDGE_SEARCH_TOOL_DEFINITION.input_schema
    assert set(schema["properties"]) == {"query", "top_k"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["top_k"]["minimum"] == 1
    assert schema["properties"]["top_k"]["maximum"] == 5


@pytest.mark.anyio
async def test_executor_ignores_forged_metadata_and_uses_bound_identity() -> None:
    workspace_id, base_id, actor_id = uuid4(), uuid4(), uuid4()
    result = KnowledgeSearchResult("query", [_item(base_id)], 1, "model")
    retrieval = SimpleNamespace(search=AsyncMock(return_value=result))
    evidence = KnowledgeEvidenceCollector()
    executor = KnowledgeSearchToolExecutor(
        retrieval,
        workspace_id=workspace_id,
        knowledge_base_id=base_id,
        actor_user_id=actor_id,
        limiter=KnowledgeToolCallLimiter(2),
        evidence=evidence,
    )

    response = await executor.execute(
        ToolExecutionRequest(
            tool_name="knowledge_search",
            arguments={"query": "query", "top_k": 1},
            metadata={
                "workspace_id": str(uuid4()),
                "knowledge_base_id": str(uuid4()),
                "actor_user_id": str(uuid4()),
            },
        )
    )

    retrieval.search.assert_awaited_once_with(workspace_id, base_id, actor_id, "query", 1, None)
    assert response.output["results"][0]["filename"] == "evidence.txt"
    assert len(evidence.snapshot()) == 1


@pytest.mark.anyio
async def test_call_limit_is_atomic_under_concurrent_invocations() -> None:
    workspace_id, base_id, actor_id = uuid4(), uuid4(), uuid4()

    async def search(*args):
        await asyncio.sleep(0)
        return KnowledgeSearchResult("query", [], 0, "model")

    retrieval = SimpleNamespace(search=search)
    limiter = KnowledgeToolCallLimiter(2)
    executor = KnowledgeSearchToolExecutor(
        retrieval,
        workspace_id=workspace_id,
        knowledge_base_id=base_id,
        actor_user_id=actor_id,
        limiter=limiter,
        evidence=KnowledgeEvidenceCollector(),
    )
    request = ToolExecutionRequest(tool_name="knowledge_search", arguments={"query": "query"})

    results = await asyncio.gather(
        *(executor.execute(request) for _ in range(3)),
        return_exceptions=True,
    )

    errors = [result for result in results if isinstance(result, ToolExecutionError)]
    assert len(errors) == 1
    assert errors[0].code == "knowledge_tool_call_limit_exceeded"
    assert limiter.calls == 2


@pytest.mark.anyio
async def test_executor_returns_safe_error_without_internal_message() -> None:
    async def search(*args):
        raise RuntimeError("postgresql://secret-password@internal")

    executor = KnowledgeSearchToolExecutor(
        SimpleNamespace(search=search),
        workspace_id=uuid4(),
        knowledge_base_id=uuid4(),
        actor_user_id=uuid4(),
        limiter=KnowledgeToolCallLimiter(1),
        evidence=KnowledgeEvidenceCollector(),
    )

    with pytest.raises(ToolExecutionError) as error_info:
        await executor.execute(
            ToolExecutionRequest(tool_name="knowledge_search", arguments={"query": "query"})
        )
    assert error_info.value.message == "Knowledge search is unavailable."
    assert "secret-password" not in str(error_info.value)
