"""Isolated knowledge tools for one workflow AGENT node execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import suppress
from uuid import UUID

from langchain_core.tools import BaseTool

from app.core.config import settings
from app.services.agent_runtime import AgentExecutionRequest, AgentRunner, AgentRuntimeError
from app.services.agent_runtime.runner.implementations import LangGraphToolAdapter
from app.services.knowledge.agent_service import _deduplicate_evidence, _extract_answer_text
from app.services.knowledge.agent_tool import (
    KNOWLEDGE_SEARCH_TOOL_DEFINITION,
    KnowledgeEvidenceCollector,
    KnowledgeSearchToolExecutor,
    KnowledgeToolCallLimiter,
)
from app.services.knowledge.retrieval_service import KnowledgeRetrievalService
from app.services.tool import (
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionService,
    ToolRegistry,
)
from app.services.tool.definition.validation import ToolSchemaValidator
from app.services.tool.execution.observer import ToolExecutionObserver
from app.services.workflow.execution.executor.contract import NodeExecutionContext

RunnerFactory = Callable[[Sequence[BaseTool], int], AgentRunner]


class _RedactedToolObserver:
    """Keep tool trace linkage while excluding raw executor error messages."""

    def __init__(self, delegate: ToolExecutionObserver) -> None:
        self._delegate = delegate

    async def start_tool(self, request: ToolExecutionRequest) -> None:
        await self._delegate.start_tool(request)

    async def complete_tool(
        self, request: ToolExecutionRequest, result: ToolExecutionResult
    ) -> None:
        await self._delegate.complete_tool(request, result)

    async def fail_tool(self, request: ToolExecutionRequest, error: ToolExecutionError) -> None:
        await self._delegate.fail_tool(
            request,
            ToolExecutionError(
                code="knowledge_agent_tool_failed",
                message="Knowledge Agent tool execution failed.",
                retryable=False,
            ),
        )


class WorkflowAgentKnowledgeComposition:
    """Copy base registrations and bind trusted identity only to a local tool."""

    def __init__(
        self,
        retrieval: KnowledgeRetrievalService,
        base_registry: ToolRegistry,
        runner_factory: RunnerFactory,
        *,
        tool_observer: ToolExecutionObserver | None = None,
        timeout_seconds: float = settings.KNOWLEDGE_AGENT_TIMEOUT_SECONDS,
        maximum_calls: int = settings.KNOWLEDGE_AGENT_MAX_TOOL_CALLS,
    ) -> None:
        self._retrieval = retrieval
        self._base_registry = base_registry
        self._runner_factory = runner_factory
        self._tool_observer = tool_observer
        self._timeout = timeout_seconds
        self._maximum_calls = maximum_calls

    async def run(
        self,
        knowledge_base_id: str,
        request: AgentExecutionRequest,
        context: NodeExecutionContext,
    ) -> dict[str, object]:
        try:
            async with asyncio.timeout(self._timeout):
                return await self._run(knowledge_base_id, request, context)
        except TimeoutError:
            raise AgentRuntimeError(
                "knowledge_agent_timeout", "Knowledge Agent timed out."
            ) from None
        except AgentRuntimeError as error:
            if error.code.startswith("knowledge_agent_"):
                raise
            raise AgentRuntimeError(
                "knowledge_agent_execution_failed", "Knowledge Agent execution failed."
            ) from None
        except Exception:
            raise AgentRuntimeError(
                "knowledge_agent_execution_failed", "Knowledge Agent execution failed."
            ) from None

    async def _run(
        self,
        knowledge_base_id: str,
        request: AgentExecutionRequest,
        context: NodeExecutionContext,
    ) -> dict[str, object]:
        if context.workspace_id is None or context.actor_user_id is None:
            raise AgentRuntimeError(
                "knowledge_agent_identity_missing", "Knowledge Agent requires trusted run identity."
            )
        try:
            base_id = UUID(knowledge_base_id)
        except (TypeError, ValueError):
            raise AgentRuntimeError(
                "knowledge_agent_config_invalid", "Knowledge Agent configuration is invalid."
            ) from None
        # Reject name collisions before any LLM invocation or shared-state mutation.
        if any(
            d.name == KNOWLEDGE_SEARCH_TOOL_DEFINITION.name
            for d in self._base_registry.definitions()
        ):
            raise AgentRuntimeError(
                "knowledge_agent_tool_conflict", "Knowledge Agent tool name is unavailable."
            )
        await self._retrieval.authorize_scope(context.workspace_id, base_id, context.actor_user_id)
        evidence = KnowledgeEvidenceCollector()
        limiter = KnowledgeToolCallLimiter(self._maximum_calls)
        registry = ToolRegistry()
        for definition in self._base_registry.definitions():
            registration = self._base_registry.resolve(definition.name)
            registry.register(registration.definition, registration.executor)
        registry.register(
            KNOWLEDGE_SEARCH_TOOL_DEFINITION,
            KnowledgeSearchToolExecutor(
                self._retrieval,
                workspace_id=context.workspace_id,
                knowledge_base_id=base_id,
                actor_user_id=context.actor_user_id,
                limiter=limiter,
                evidence=evidence,
            ),
        )
        service = ToolExecutionService(
            registry,
            ToolSchemaValidator(),
            observer=(
                _RedactedToolObserver(self._tool_observer)
                if self._tool_observer is not None
                else None
            ),
        )
        adapter = LangGraphToolAdapter(service)
        tools = tuple(adapter.adapt(d) for d in registry.definitions())
        runner = self._runner_factory(tools, self._maximum_calls * 2 + 16)
        try:
            result = await runner.run(request)
            items = _deduplicate_evidence(evidence.snapshot())
            if not items:
                return {
                    "answer": "The knowledge base does not contain supporting information for this question.",
                    "status": "no_evidence",
                    "sources": [],
                }
            answer = _extract_answer_text(result.output)
            if answer is None:
                raise AgentRuntimeError(
                    "knowledge_agent_invalid_response",
                    "Knowledge Agent returned an invalid response.",
                )
            return {
                "answer": answer,
                "status": "answered",
                "sources": [
                    {
                        "chunk_id": str(item.chunk_id),
                        "document_id": str(item.document_id),
                        "filename": item.filename,
                        "page_start": item.page_start,
                        "page_end": item.page_end,
                        "similarity_score": item.similarity_score,
                    }
                    for item in items
                ],
            }
        finally:
            closer = getattr(runner, "aclose", None)
            if closer is not None:
                with suppress(Exception):
                    await closer()
