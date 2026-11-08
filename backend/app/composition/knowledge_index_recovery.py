"""Isolated composition for periodic knowledge index recovery."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, settings
from app.integrations.celery.knowledge_index_dispatcher import CeleryKnowledgeIndexDispatcher
from app.services.knowledge.index_recovery import KnowledgeIndexRecoveryScanner
from app.worker.celery_app import celery_app


@asynccontextmanager
async def open_knowledge_index_recovery_scanner(
    scanner_settings: Settings = settings,
) -> AsyncIterator[KnowledgeIndexRecoveryScanner]:
    engine = create_async_engine(scanner_settings.DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield KnowledgeIndexRecoveryScanner(
            session_factory,
            CeleryKnowledgeIndexDispatcher(celery_app),
            batch_size=scanner_settings.KNOWLEDGE_INDEX_RECOVERY_BATCH_SIZE,
            redispatch_delay=timedelta(
                seconds=scanner_settings.KNOWLEDGE_INDEX_RECOVERY_REDISPATCH_DELAY_SECONDS
            ),
        )
    finally:
        await engine.dispose()
