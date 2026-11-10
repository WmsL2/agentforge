"""Request-bound knowledge search tool for the Knowledge Agent."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.core.exceptions import AppException
from app.services.knowledge.retrieval_service import (
    KnowledgeRetrievalService,
    KnowledgeSearchItem,
)
from app.services.tool import (
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
)

KNOWLEDGE_SEARCH_TOOL_DEFINITION = ToolDefinition(
    name="knowledge_search",
    description=(
        "Search the knowledge base bound to this request. Use the returned document chunks "
        "as the only evidence for the answer."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 2000},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 5, "default": 5},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)


class KnowledgeToolCallLimiter:
    """Atomically reserve a bounded number of calls within one HTTP request."""

    def __init__(self, maximum_calls: int) -> None:
        self._maximum_calls = maximum_calls
        self._calls = 0
        self._lock = asyncio.Lock()

    @property
    def calls(self) -> int:
        return self._calls

    async def reserve(self) -> None:
        async with self._lock:
            if self._calls >= self._maximum_calls:
                raise ToolExecutionError(
                    code="knowledge_tool_call_limit_exceeded",
                    message="Knowledge search call limit exceeded.",
                )
            self._calls += 1


class KnowledgeEvidenceCollector:
    """Collect only evidence returned by successful backend tool executions."""

    def __init__(self) -> None:
        self._items: list[KnowledgeSearchItem] = []
        self._lock = asyncio.Lock()

    async def add(self, items: list[KnowledgeSearchItem]) -> None:
        async with self._lock:
            self._items.extend(items)

    def snapshot(self) -> tuple[KnowledgeSearchItem, ...]:
        return tuple(self._items)


class KnowledgeSearchToolExecutor:
    """Execute retrieval with trusted scope captured outside model arguments."""

    def __init__(
        self,
        retrieval_service: KnowledgeRetrievalService,
        *,
        workspace_id: UUID,
        knowledge_base_id: UUID,
        actor_user_id: UUID,
        limiter: KnowledgeToolCallLimiter,
        evidence: KnowledgeEvidenceCollector,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._workspace_id = workspace_id
        self._knowledge_base_id = knowledge_base_id
        self._actor_user_id = actor_user_id
        self._limiter = limiter
        self._evidence = evidence

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        await self._limiter.reserve()
        query = request.arguments.get("query")
        top_k = request.arguments.get("top_k", 5)
        if not isinstance(query, str) or isinstance(top_k, bool) or not isinstance(top_k, int):
            raise ToolExecutionError(
                code="invalid_arguments",
                message="Knowledge search arguments are invalid.",
            )

        try:
            result = await self._retrieval_service.search(
                self._workspace_id,
                self._knowledge_base_id,
                self._actor_user_id,
                query,
                top_k,
                None,
            )
        except AppException as error:
            raise ToolExecutionError(
                code=error.code.lower(),
                message="Knowledge search is unavailable.",
            ) from error
        except Exception as error:
            raise ToolExecutionError(
                code="knowledge_search_failed",
                message="Knowledge search is unavailable.",
            ) from error

        await self._evidence.add(result.results)
        return ToolExecutionResult(
            output={"results": [_tool_item(item) for item in result.results]}
        )


def _tool_item(item: KnowledgeSearchItem) -> Mapping[str, Any]:
    return {
        "chunk_id": str(item.chunk_id),
        "document_id": str(item.document_id),
        "filename": item.filename,
        "content": item.content,
        "page_start": item.page_start,
        "page_end": item.page_end,
        "similarity_score": item.similarity_score,
    }
