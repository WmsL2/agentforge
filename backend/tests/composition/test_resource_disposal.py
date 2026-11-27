"""Offline application and task-local resource disposal contracts."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import main
from app.db import session as sessions


@pytest.mark.anyio
@pytest.mark.parametrize(
    "stage", ["success", "redis_start", "tool_enter", "body", "tool_exit", "cancel"]
)
@pytest.mark.parametrize("redis_close_fails", [False, True])
async def test_api_lifespan_disposes_independent_resources(monkeypatch, stage, redis_close_fails):
    events = []
    failure = asyncio.CancelledError() if stage == "cancel" else RuntimeError(stage)
    redis_error = RuntimeError("redis cleanup")

    async def connect():
        if stage == "redis_start":
            raise failure

    async def redis_close():
        events.append("redis")
        if redis_close_fails:
            raise redis_error

    async def db_close():
        events.append("db")

    @asynccontextmanager
    async def tools(_):
        if stage == "tool_enter":
            raise failure
        try:
            yield "registry"
        finally:
            events.append("tools")
            if stage == "tool_exit":
                raise failure
            if stage in {"body", "cancel"}:
                raise RuntimeError("secondary tool cleanup error")

    monkeypatch.setattr(main, "RedisClient", lambda: MagicMock(connect=connect, close=redis_close))
    monkeypatch.setattr(main, "close_db", db_close)
    monkeypatch.setattr(main, "open_tool_platform", tools)

    async def run():
        async with main.lifespan(main.app) as state:
            assert state["tool_registry"] == "registry"
            if stage in {"body", "cancel"}:
                raise failure

    expected = failure if stage != "success" else redis_error if redis_close_fails else None
    if expected is None:
        await run()
    else:
        with pytest.raises(type(expected)) as caught:
            await run()
        assert caught.value is expected
    assert events == (
        ["redis", "db"] if stage in {"redis_start", "tool_enter"} else ["tools", "redis", "db"]
    )


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["factory", "entry", "body", "exit", "cancel", "success"])
@pytest.mark.parametrize("dispose_fails", [False, True])
async def test_worker_disposes_after_session_and_preserves_primary(
    monkeypatch, stage, dispose_fails
):
    events = []
    primary = asyncio.CancelledError() if stage == "cancel" else RuntimeError(stage)
    disposal = RuntimeError("dispose secondary")

    async def dispose():
        events.append("dispose")
        if dispose_fails:
            raise disposal

    async def enter():
        if stage == "entry":
            raise primary
        return db

    async def exit_session(*_):
        events.append("session exit")
        if stage == "exit":
            raise primary
        if stage in {"body", "cancel"}:
            raise RuntimeError("session exit secondary")

    db = MagicMock(commit=AsyncMock(), rollback=AsyncMock())
    db.__aenter__.side_effect = enter
    db.__aexit__.side_effect = exit_session
    engine = MagicMock(dispose=dispose)
    create_engine = MagicMock(return_value=engine)
    monkeypatch.setattr(sessions, "create_async_engine", create_engine)
    factory = MagicMock(return_value=db)
    if stage == "factory":
        factory.side_effect = primary
    monkeypatch.setattr(sessions, "async_sessionmaker", MagicMock(return_value=factory))

    async def run():
        async with sessions.get_worker_db_context():
            if stage in {"body", "cancel"}:
                raise primary

    expected = primary if stage != "success" else disposal if dispose_fails else None
    if expected is None:
        await run()
    else:
        with pytest.raises(type(expected)) as caught:
            await run()
        assert caught.value is expected
    assert events == (["dispose"] if stage in {"entry", "factory"} else ["session exit", "dispose"])
    assert create_engine.call_args.kwargs["poolclass"] is sessions.NullPool
    assert db.commit.await_count == int(stage in {"exit", "success"})
    if stage == "body":
        db.rollback.assert_awaited_once()


COMPOSITION_ENTRIES = [
    ("workflow_worker", "open_workflow_worker"),
    ("knowledge_index_worker", "open_knowledge_index_worker"),
    ("workflow_recovery", "open_workflow_recovery_scanner"),
    ("knowledge_index_recovery", "open_knowledge_index_recovery_scanner"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("name,entry", COMPOSITION_ENTRIES)
@pytest.mark.parametrize(
    "stage,dispose_fails",
    [
        ("engine", False),
        ("factory", False),
        ("construction", False),
        ("success", False),
        ("body", False),
        ("cancel", False),
        ("body", True),
        ("cancel", True),
        ("success", True),
    ],
)
async def test_composition_disposal_paths(monkeypatch, caplog, name, entry, stage, dispose_fails):
    from importlib import import_module

    module = import_module(f"app.composition.{name}")
    primary = asyncio.CancelledError() if stage == "cancel" else RuntimeError(stage)
    cleanup = RuntimeError("synthetic-private-disposal-detail")
    events = []
    session_factory = MagicMock()

    def create_engine(*args, **kwargs):
        events.append("engine")
        if stage == "engine":
            raise primary
        return engine

    def make_factory(*args, **kwargs):
        events.append("factory")
        if stage == "factory":
            raise primary
        return session_factory

    async def dispose():
        events.append("dispose")
        if dispose_fails:
            raise cleanup

    engine = MagicMock(dispose=AsyncMock(side_effect=dispose))
    engine_factory = MagicMock(side_effect=create_engine)
    factory_constructor = MagicMock(side_effect=make_factory)
    monkeypatch.setattr(module, "create_async_engine", engine_factory)
    monkeypatch.setattr(module, "async_sessionmaker", factory_constructor)
    if name == "workflow_worker":

        @asynccontextmanager
        async def tool_platform(_):
            events.append("mcp enter")
            try:
                yield MagicMock()
            finally:
                events.append("mcp exit")

        monkeypatch.setattr(module, "open_tool_platform", tool_platform)
    if stage == "construction":
        constructor = {
            "workflow_worker": "BackgroundRunExecutor",
            "knowledge_index_worker": "KnowledgeIndexExecutor",
            "workflow_recovery": "WorkflowRecoveryScanner",
            "knowledge_index_recovery": "KnowledgeIndexRecoveryScanner",
        }[name]
        monkeypatch.setattr(module, constructor, MagicMock(side_effect=primary))

    async def run():
        async with getattr(module, entry)():
            events.append("body")
            engine.dispose.assert_not_awaited()
            if stage in {"body", "cancel"}:
                raise primary

    expected = (cleanup if dispose_fails else None) if stage == "success" else primary
    if expected is None:
        await run()
    else:
        with pytest.raises(type(expected)) as caught:
            await run()
        assert caught.value is expected

    engine_factory.assert_called_once()
    assert engine_factory.call_args.kwargs["poolclass"] is sessions.NullPool
    if stage == "engine":
        factory_constructor.assert_not_called()
        engine.dispose.assert_not_awaited()
        assert events == ["engine"]
        return
    factory_constructor.assert_called_once_with(
        engine, class_=module.AsyncSession, expire_on_commit=False
    )
    engine.dispose.assert_awaited_once()
    order = ["engine", "factory"]
    if stage != "factory":
        if name == "workflow_worker":
            order.append("mcp enter")
        if stage != "construction":
            order.append("body")
        if name == "workflow_worker":
            order.append("mcp exit")
    assert events == [*order, "dispose"]
    assert "synthetic-private-disposal-detail" not in caplog.text
    if dispose_fails and expected is primary:
        assert "COMPOSITION_ENGINE_DISPOSE_FAILED" in caplog.messages


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["entry", "exit"])
async def test_workflow_mcp_boundary_precedes_disposal(monkeypatch, stage):
    from app.composition import workflow_worker

    events = []
    failure = RuntimeError("synthetic MCP failure")
    cleanup = RuntimeError("synthetic engine cleanup failure")

    @asynccontextmanager
    async def tools(_):
        events.append("entry")
        if stage == "entry":
            raise failure
        yield MagicMock()
        events.append("exit")
        raise failure

    async def dispose():
        events.append("dispose")
        raise cleanup

    engine = MagicMock(dispose=AsyncMock(side_effect=dispose))
    monkeypatch.setattr(workflow_worker, "create_async_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(workflow_worker, "async_sessionmaker", MagicMock())
    monkeypatch.setattr(workflow_worker, "open_tool_platform", tools)
    with pytest.raises(RuntimeError) as caught:
        async with workflow_worker.open_workflow_worker():
            events.append("body")
    assert caught.value is failure
    engine.dispose.assert_awaited_once()
    assert events == (
        ["entry", "dispose"] if stage == "entry" else ["entry", "body", "exit", "dispose"]
    )


@pytest.mark.anyio
async def test_api_cleanup_cancellation_propagates_after_other_cleanup_failure(monkeypatch):
    cancel = asyncio.CancelledError()

    @asynccontextmanager
    async def tools(_):
        yield MagicMock()

    redis_close = AsyncMock(side_effect=RuntimeError("synthetic close failure"))
    monkeypatch.setattr(
        main, "RedisClient", lambda: MagicMock(connect=AsyncMock(), close=redis_close)
    )
    monkeypatch.setattr(main, "close_db", AsyncMock(side_effect=cancel))
    monkeypatch.setattr(main, "open_tool_platform", tools)
    with pytest.raises(asyncio.CancelledError) as caught:
        async with main.lifespan(main.app):
            pass
    assert caught.value is cancel
    redis_close.assert_awaited_once()
    main.close_db.assert_awaited_once()
