"""Bounded read-only readiness checks using the existing database session factory."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_maker

PROBE_TIMEOUT_SECONDS = 2.0
CLEANUP_TIMEOUT_SECONDS = 0.25
HealthSessionFactory = Callable[[], AsyncSession]


def get_health_session_factory() -> HealthSessionFactory:
    """DI boundary: no new engine, pool, or request-session commit lifecycle."""
    return async_session_maker


def build_health_response(
    status: str, checks: dict[str, Any] | None = None, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "service": settings.PROJECT_NAME,
    }
    if checks is not None:
        response["checks"] = checks
    if details is not None:
        response["details"] = details
    return response


async def probe_database(factory: HealthSessionFactory) -> dict[str, Any]:
    start = perf_counter()
    session = None
    error = None
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            session = factory()
            await session.execute(text("SELECT 1"))
    except TimeoutError:
        error = "DATABASE_TIMEOUT"
    except Exception:
        error = "DATABASE_CONNECTION_FAILED"
    finally:
        if session is not None:
            try:
                # close rolls back the read transaction; never commit a health session.
                async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
                    await session.close()
            except TimeoutError:
                error = error or "DATABASE_CLEANUP_TIMEOUT"
            except Exception:
                error = error or "DATABASE_CLEANUP_FAILED"
    result: dict[str, Any] = {
        "status": "unhealthy" if error else "healthy",
        "type": "postgresql",
        "latency_ms": round((perf_counter() - start) * 1000, 2),
    }
    if error:
        result["error"] = error
    return result


async def probe_redis(redis: Any) -> dict[str, Any]:
    start = perf_counter()
    error = None
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            if redis is None:
                error = "REDIS_UNAVAILABLE"
            elif not await redis.ping():
                error = "REDIS_PING_FAILED"
    except TimeoutError:
        error = "REDIS_TIMEOUT"
    except Exception:
        error = "REDIS_CONNECTION_FAILED"
    result: dict[str, Any] = {
        "status": "unhealthy" if error else "healthy",
        "latency_ms": round((perf_counter() - start) * 1000, 2),
    }
    if error:
        result["error"] = error
    return result


def capability_checks() -> dict[str, dict[str, Any]]:
    llm = bool(settings.LLM_PROVIDER.strip() and settings.LLM_API_KEY and settings.AI_MODEL.strip())
    embedding = bool(
        settings.EMBEDDING_API_KEY
        and settings.EMBEDDING_MODEL.strip()
        and settings.EMBEDDING_DIMENSIONS > 0
    )

    def capability(configured: bool) -> dict[str, Any]:
        return {
            "status": "configured" if configured else "not_configured",
            "connectivity_checked": False,
        }

    return {
        "llm": capability(llm),
        "embedding": capability(embedding),
        "worker": capability(bool(settings.CELERY_BROKER_URL)),
        "knowledge_agent": {
            **capability(settings.KNOWLEDGE_AGENT_ENABLED and llm and embedding),
            "enabled": settings.KNOWLEDGE_AGENT_ENABLED,
        },
    }
