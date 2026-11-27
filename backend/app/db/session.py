"""Async PostgreSQL database session."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def _managed_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Shared session lifecycle: commit on success, rollback on error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            logger.exception("DB session error, rolling back")
            try:
                await session.rollback()
            except Exception:
                logger.exception("DB session rollback failed")
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session for FastAPI dependency injection.

    Use this with FastAPI Depends().
    """
    async with _managed_session(async_session_maker) as session:
        yield session


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session as context manager.

    Use this with 'async with' for manual session management (e.g., WebSockets).
    """
    async with _managed_session(async_session_maker) as session:
        yield session


@asynccontextmanager
async def get_worker_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Get a short-lived async session for background workers (Celery/ARQ).

    Creates a fresh engine with NullPool on every call so there are no
    cross-fork / cross-event-loop connection issues.  The engine is disposed
    automatically when the context manager exits.
    """
    worker_engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    transaction_error: BaseException | None = None
    primary: BaseException | None = None
    try:
        factory = async_sessionmaker(
            worker_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException as error:
                transaction_error = error
                try:
                    await session.rollback()
                except BaseException:
                    logger.error("WORKER_DB_ROLLBACK_FAILED")
                raise
    except BaseException as error:
        primary = transaction_error if transaction_error is not None else error
        if primary is not error:
            logger.error("WORKER_DB_SESSION_EXIT_FAILED")
            raise primary from None
        raise
    finally:
        try:
            await worker_engine.dispose()
        except BaseException:
            logger.error("WORKER_DB_DISPOSE_FAILED")
            if primary is None:
                raise


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
