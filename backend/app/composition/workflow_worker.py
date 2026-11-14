"""Per-task composition root for Celery workflow execution."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.composition.tool_platform import open_tool_platform
from app.core.config import Settings, settings
from app.services.agent_runtime.runner.implementations import (
    LangGraphAgentRunner,
    LangGraphToolAdapter,
)
from app.services.knowledge.embedding import OpenAIEmbeddingProvider
from app.services.knowledge.retrieval_service import KnowledgeRetrievalService
from app.services.tool import ToolExecutionService
from app.services.tool.definition.validation import ToolSchemaValidator
from app.services.workflow import (
    AgentNodeExecutor,
    ApprovalNodeExecutor,
    BackgroundRunExecutor,
    DeterministicNodeExecutor,
    DispatchingNodeExecutor,
    KnowledgeNodeExecutor,
    WorkflowEngine,
)
from app.services.workflow.application.observability import (
    SQLAlchemyWorkflowExecutionObserver,
    WorkflowToolExecutionObserver,
)
from app.services.workflow.execution.executor.agent.knowledge import (
    WorkflowAgentKnowledgeComposition,
)


@asynccontextmanager
async def open_workflow_worker(
    worker_settings: Settings = settings,
) -> AsyncIterator[BackgroundRunExecutor]:
    """Build one isolated workflow runtime and release all task resources."""
    engine = create_async_engine(
        worker_settings.DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        observer = SQLAlchemyWorkflowExecutionObserver(session_factory)

        def provider_factory() -> OpenAIEmbeddingProvider:
            return OpenAIEmbeddingProvider(
                api_key=worker_settings.EMBEDDING_API_KEY,
                model=worker_settings.EMBEDDING_MODEL,
                dimensions=worker_settings.EMBEDDING_DIMENSIONS,
                base_url=worker_settings.EMBEDDING_BASE_URL,
                batch_size=worker_settings.EMBEDDING_BATCH_SIZE,
                timeout_seconds=worker_settings.EMBEDDING_REQUEST_TIMEOUT_SECONDS,
                max_retries=worker_settings.EMBEDDING_MAX_RETRIES,
            )

        retrieval_service = KnowledgeRetrievalService(
            session_factory,
            provider_factory,
            embedding_model=worker_settings.EMBEDDING_MODEL,
            embedding_dimensions=worker_settings.EMBEDDING_DIMENSIONS,
            embedding_timeout_seconds=worker_settings.EMBEDDING_REQUEST_TIMEOUT_SECONDS,
            db_statement_timeout_ms=worker_settings.KNOWLEDGE_RETRIEVAL_DB_TIMEOUT_MS,
        )
        async with open_tool_platform(worker_settings.MCP_STDIO_SERVERS) as registry:
            tool_service = ToolExecutionService(
                registry=registry,
                validator=ToolSchemaValidator(),
                observer=WorkflowToolExecutionObserver(observer),
            )
            adapter = LangGraphToolAdapter(tool_service)
            runner = LangGraphAgentRunner(
                tools=tuple(adapter.adapt(definition) for definition in registry.definitions())
            )
            node_executor = DispatchingNodeExecutor(
                deterministic_executor=DeterministicNodeExecutor(),
                agent_executor=AgentNodeExecutor(
                    {"langgraph": runner},
                    observer=observer,
                    knowledge=WorkflowAgentKnowledgeComposition(
                        retrieval_service,
                        registry,
                        lambda tools, limit: LangGraphAgentRunner(
                            tools=tools, recursion_limit=limit
                        ),
                        tool_observer=WorkflowToolExecutionObserver(observer),
                        timeout_seconds=worker_settings.KNOWLEDGE_AGENT_TIMEOUT_SECONDS,
                        maximum_calls=worker_settings.KNOWLEDGE_AGENT_MAX_TOOL_CALLS,
                    ),
                ),
                approval_executor=ApprovalNodeExecutor(observer=observer),
                knowledge_executor=KnowledgeNodeExecutor(retrieval_service),
            )
            workflow_engine = WorkflowEngine(node_executor, observer=observer)
            yield BackgroundRunExecutor(
                session_factory,
                workflow_engine,
                lease_duration=timedelta(seconds=worker_settings.WORKFLOW_BACKGROUND_LEASE_SECONDS),
            )
    finally:
        await engine.dispose()
