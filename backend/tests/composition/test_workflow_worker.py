"""Per-task workflow worker composition tests."""

from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from sqlalchemy.pool import NullPool

from app.composition.workflow_worker import open_workflow_worker
from app.core.config import Settings
from app.services.tool import ToolRegistry
from app.services.workflow import (
    AgentNodeExecutor,
    ApprovalNodeExecutor,
    DeterministicNodeExecutor,
)


def worker_settings(**values: object) -> Settings:
    return Settings(
        _env_file=None,
        POSTGRES_HOST="localhost",
        POSTGRES_PASSWORD="test",
        POSTGRES_DB="agentforge_worker_unit",
        MCP_STDIO_SERVERS=[],
        **values,
    )


@pytest.mark.anyio
async def test_composition_uses_one_nullpool_factory_and_configured_lease() -> None:
    config = worker_settings(WORKFLOW_BACKGROUND_LEASE_SECONDS=37)

    async with open_workflow_worker(config) as executor:
        factory = executor._session_factory
        database_engine = factory.kw["bind"]
        workflow_engine = executor._engine
        dispatcher = workflow_engine._executor

        assert isinstance(database_engine.pool, NullPool)
        assert executor._lease_duration == timedelta(seconds=37)
        assert workflow_engine._observer._session_factory is factory
        assert isinstance(dispatcher._deterministic_executor, DeterministicNodeExecutor)
        assert isinstance(dispatcher._agent_executor, AgentNodeExecutor)
        assert isinstance(dispatcher._approval_executor, ApprovalNodeExecutor)
        assert dispatcher._agent_executor._observer is workflow_engine._observer
        assert dispatcher._approval_executor._observer is workflow_engine._observer

    assert database_engine.pool.status() == "NullPool"


@pytest.mark.anyio
async def test_composition_disposes_engine_when_mcp_startup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.composition import workflow_worker

    disposed = False

    class FakeEngine:
        async def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    def fake_create_engine(*args, **kwargs) -> FakeEngine:
        return FakeEngine()

    class FailingPlatform:
        async def __aenter__(self):
            raise RuntimeError("MCP startup failed")

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(workflow_worker, "create_async_engine", fake_create_engine)
    monkeypatch.setattr(workflow_worker, "open_tool_platform", lambda servers: FailingPlatform())

    with pytest.raises(RuntimeError, match="MCP startup failed"):
        async with open_workflow_worker(worker_settings()):
            pass

    assert disposed


@pytest.mark.anyio
async def test_composition_closes_mcp_and_disposes_engine_when_execution_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.composition import workflow_worker

    disposed = False
    platform_closed = False

    class FakeEngine:
        async def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    database_engine = FakeEngine()

    @asynccontextmanager
    async def fake_platform(servers):
        nonlocal platform_closed
        try:
            yield ToolRegistry()
        finally:
            platform_closed = True

    monkeypatch.setattr(
        workflow_worker, "create_async_engine", lambda *args, **kwargs: database_engine
    )
    monkeypatch.setattr(workflow_worker, "open_tool_platform", fake_platform)

    with pytest.raises(RuntimeError, match="engine failed"):
        async with open_workflow_worker(worker_settings()):
            raise RuntimeError("engine failed")

    assert platform_closed
    assert disposed
