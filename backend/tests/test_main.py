"""Tests for FastAPI application lifespan composition."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

import app.main as main_module
from app.core.config import MCPStdioServerSettings
from app.services.tool import ToolRegistry


class FakeRedisClient:
    """A lifespan Redis replacement that records lifecycle calls."""

    def __init__(self) -> None:
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_lifespan_exposes_shared_registry_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedisClient()
    entered = False
    exited = False
    close_database = AsyncMock()

    @asynccontextmanager
    async def fake_tool_platform(servers: Sequence[MCPStdioServerSettings]) -> AsyncIterator[ToolRegistry]:
        nonlocal entered, exited
        entered = True
        try:
            yield ToolRegistry()
        finally:
            exited = True

    monkeypatch.setattr(main_module, "RedisClient", lambda: redis)
    monkeypatch.setattr(main_module, "open_tool_platform", fake_tool_platform)
    monkeypatch.setattr(main_module, "close_db", close_database)

    async with main_module.lifespan(FastAPI()) as state:
        assert state["redis"] is redis
        assert isinstance(state["tool_registry"], ToolRegistry)
        assert entered is True

    assert exited is True
    assert redis.closed is True
    close_database.assert_awaited_once()


@pytest.mark.anyio
async def test_lifespan_cleans_up_redis_when_tool_platform_startup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedisClient()
    close_database = AsyncMock()

    @asynccontextmanager
    async def failing_tool_platform(servers: Sequence[MCPStdioServerSettings]) -> AsyncIterator[ToolRegistry]:
        raise RuntimeError("MCP startup failed")
        yield ToolRegistry()

    monkeypatch.setattr(main_module, "RedisClient", lambda: redis)
    monkeypatch.setattr(main_module, "open_tool_platform", failing_tool_platform)
    monkeypatch.setattr(main_module, "close_db", close_database)

    with pytest.raises(RuntimeError, match="MCP startup failed"):
        async with main_module.lifespan(FastAPI()):
            pass

    assert redis.closed is True
    close_database.assert_awaited_once()
