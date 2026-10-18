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
from app.services.tool import ToolExecutionService
from app.services.tool.definition.validation import ToolSchemaValidator
from app.services.workflow import (
    AgentNodeExecutor,
    ApprovalNodeExecutor,
    BackgroundRunExecutor,
    DeterministicNodeExecutor,
    DispatchingNodeExecutor,
    WorkflowEngine,
)
from app.services.workflow.application.observability import (
    SQLAlchemyWorkflowExecutionObserver,
    WorkflowToolExecutionObserver,
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
                agent_executor=AgentNodeExecutor({"langgraph": runner}, observer=observer),
                approval_executor=ApprovalNodeExecutor(observer=observer),
            )
            workflow_engine = WorkflowEngine(node_executor, observer=observer)
            yield BackgroundRunExecutor(
                session_factory,
                workflow_engine,
                lease_duration=timedelta(seconds=worker_settings.WORKFLOW_BACKGROUND_LEASE_SECONDS),
            )
    finally:
        await engine.dispose()
