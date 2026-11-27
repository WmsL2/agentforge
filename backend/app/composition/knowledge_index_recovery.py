"""Isolated composition for periodic knowledge index recovery."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, settings
from app.integrations.celery.knowledge_index_dispatcher import CeleryKnowledgeIndexDispatcher
from app.services.knowledge.index_recovery import KnowledgeIndexRecoveryScanner
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@asynccontextmanager
async def open_knowledge_index_recovery_scanner(
    scanner_settings: Settings = settings,
) -> AsyncIterator[KnowledgeIndexRecoveryScanner]:
    engine = create_async_engine(scanner_settings.DATABASE_URL, poolclass=NullPool)
    failed = False
    try:
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        yield KnowledgeIndexRecoveryScanner(
            session_factory,
            CeleryKnowledgeIndexDispatcher(celery_app),
            batch_size=scanner_settings.KNOWLEDGE_INDEX_RECOVERY_BATCH_SIZE,
            redispatch_delay=timedelta(
                seconds=scanner_settings.KNOWLEDGE_INDEX_RECOVERY_REDISPATCH_DELAY_SECONDS
            ),
        )
    except BaseException:
        failed = True
        raise
    finally:
        try:
            await engine.dispose()
        except BaseException:
            logger.error("COMPOSITION_ENGINE_DISPOSE_FAILED")
            if not failed:
                raise
