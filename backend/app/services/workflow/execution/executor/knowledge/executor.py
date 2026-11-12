"""Authorized knowledge retrieval for one workflow node."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.services.knowledge.retrieval_service import KnowledgeRetrievalService
from app.services.workflow.definition.model.domain import WorkflowNode, WorkflowNodeKind
from app.services.workflow.execution.executor.contract import (
    NodeExecutionContext,
    NodeExecutionResult,
)


class KnowledgeNodeExecutionError(RuntimeError):
    """A stable, non-sensitive workflow knowledge-node failure."""


class KnowledgeNodeExecutor:
    """Resolve a validated query and delegate to the shared retrieval boundary."""

    def __init__(self, retrieval_service: KnowledgeRetrievalService) -> None:
        self._retrieval_service = retrieval_service

    async def execute(
        self,
        node: WorkflowNode,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        if node.kind is not WorkflowNodeKind.KNOWLEDGE:
            raise KnowledgeNodeExecutionError("Knowledge executor received an invalid node kind.")
        if context.workspace_id is None or context.actor_user_id is None:
            raise KnowledgeNodeExecutionError("Knowledge node requires trusted run identity.")

        try:
            knowledge_base_id = UUID(node.config["knowledge_base_id"])
            query = self._resolve_query(node.config, context)
            top_k = node.config.get("top_k", 5)
            if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 5:
                raise ValueError("Invalid top_k")
        except (KeyError, TypeError, ValueError) as error:
            raise KnowledgeNodeExecutionError("Knowledge node configuration is invalid.") from error

        try:
            result = await self._retrieval_service.search(
                context.workspace_id,
                knowledge_base_id,
                context.actor_user_id,
                query,
                top_k,
                None,
            )
        except Exception as error:
            raise KnowledgeNodeExecutionError("Knowledge retrieval failed.") from error

        return NodeExecutionResult(
            output={
                "query": result.query,
                "total": result.total,
                "results": [self._serialize_item(item) for item in result.results],
            }
        )

    @staticmethod
    def _resolve_query(config: dict[str, Any], context: NodeExecutionContext) -> str:
        source = config["query_source"]
        if source == "literal":
            value = config["query"]
        elif source == "workflow_input":
            input_key = config["input_key"]
            if not isinstance(input_key, str) or not input_key.strip():
                raise ValueError("Invalid input key")
            value = context.workflow_input.get(input_key)
        else:
            raise ValueError("Invalid query source")
        if not isinstance(value, str):
            raise ValueError("Query must be a string")
        query = value.strip()
        if not query or len(query) > 2000:
            raise ValueError("Query length is invalid")
        return query

    @staticmethod
    def _serialize_item(item: Any) -> dict[str, Any]:
        return {
            "chunk_id": str(item.chunk_id),
            "document_id": str(item.document_id),
            "filename": item.filename,
            "content": item.content,
            "page_start": item.page_start,
            "page_end": item.page_end,
            "similarity_score": item.similarity_score,
        }
