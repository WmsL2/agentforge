"""Tests for trusted workflow knowledge retrieval."""

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest

from app.services.knowledge.retrieval_service import KnowledgeSearchItem, KnowledgeSearchResult
from app.services.workflow import (
    KnowledgeNodeExecutionError,
    KnowledgeNodeExecutor,
    NodeExecutionContext,
    WorkflowNode,
    WorkflowNodeKind,
)


def context(*, workflow_input=None, trusted: bool = True) -> NodeExecutionContext:
    return NodeExecutionContext(
        run_id=uuid4(),
        workflow_input=workflow_input or {},
        upstream_outputs={},
        node_outputs={},
        workspace_id=uuid4() if trusted else None,
        actor_user_id=uuid4() if trusted else None,
    )


def node(config: dict[str, object]) -> WorkflowNode:
    return WorkflowNode("knowledge", WorkflowNodeKind.KNOWLEDGE, config)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("config", "workflow_input", "expected_query"),
    [
        (
            {
                "knowledge_base_id": str(uuid4()),
                "query_source": "literal",
                "query": " fixed query ",
            },
            {},
            "fixed query",
        ),
        (
            {
                "knowledge_base_id": str(uuid4()),
                "query_source": "workflow_input",
                "input_key": "question",
                "top_k": 3,
            },
            {"question": " dynamic query ", "nested": {"question": "ignored"}},
            "dynamic query",
        ),
    ],
)
async def test_executes_literal_and_top_level_dynamic_queries(
    config: dict[str, object], workflow_input: dict[str, object], expected_query: str
) -> None:
    item = KnowledgeSearchItem(
        chunk_id=uuid4(),
        document_id=uuid4(),
        knowledge_base_id=uuid4(),
        filename="fish.pdf",
        chunk_index=0,
        content="evidence",
        start_offset=0,
        end_offset=8,
        page_start=2,
        page_end=2,
        similarity_score=0.92,
    )
    retrieval = SimpleNamespace(
        search=AsyncMock(
            return_value=KnowledgeSearchResult(expected_query, [item], 1, "embedding-model")
        )
    )
    execution_context = context(workflow_input=workflow_input)

    result = await KnowledgeNodeExecutor(retrieval).execute(node(config), execution_context)

    retrieval.search.assert_awaited_once_with(
        execution_context.workspace_id,
        ANY,
        execution_context.actor_user_id,
        expected_query,
        config.get("top_k", 5),
        None,
    )
    assert result.output == {
        "query": expected_query,
        "total": 1,
        "results": [
            {
                "chunk_id": str(item.chunk_id),
                "document_id": str(item.document_id),
                "filename": "fish.pdf",
                "content": "evidence",
                "page_start": 2,
                "page_end": 2,
                "similarity_score": 0.92,
            }
        ],
    }


@pytest.mark.anyio
async def test_empty_results_are_json_persistable() -> None:
    retrieval = SimpleNamespace(
        search=AsyncMock(return_value=KnowledgeSearchResult("q", [], 0, "model"))
    )
    result = await KnowledgeNodeExecutor(retrieval).execute(
        node(
            {
                "knowledge_base_id": str(uuid4()),
                "query_source": "literal",
                "query": "q",
            }
        ),
        context(),
    )
    assert result.output == {"query": "q", "total": 0, "results": []}


@pytest.mark.anyio
async def test_missing_identity_and_invalid_dynamic_query_fail_closed() -> None:
    retrieval = SimpleNamespace(search=AsyncMock())
    executor = KnowledgeNodeExecutor(retrieval)
    config = {
        "knowledge_base_id": str(uuid4()),
        "query_source": "workflow_input",
        "input_key": "question",
    }
    with pytest.raises(KnowledgeNodeExecutionError, match="trusted run identity"):
        await executor.execute(
            node(config), context(workflow_input={"question": "q"}, trusted=False)
        )
    with pytest.raises(KnowledgeNodeExecutionError, match="configuration is invalid"):
        await executor.execute(node(config), context(workflow_input={"question": " "}))
    retrieval.search.assert_not_awaited()


@pytest.mark.anyio
async def test_retrieval_error_is_redacted() -> None:
    retrieval = SimpleNamespace(search=AsyncMock(side_effect=RuntimeError("secret api key")))
    with pytest.raises(KnowledgeNodeExecutionError, match="Knowledge retrieval failed") as error:
        await KnowledgeNodeExecutor(retrieval).execute(
            node(
                {
                    "knowledge_base_id": str(uuid4()),
                    "query_source": "literal",
                    "query": "q",
                }
            ),
            context(),
        )
    assert "secret" not in str(error.value)
