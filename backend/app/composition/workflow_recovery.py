"""Short-lived composition root for periodic workflow recovery discovery."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, settings
from app.integrations.celery.workflow_dispatcher import CeleryWorkflowDispatcher
from app.services.workflow import WorkflowRecoveryScanner
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@asynccontextmanager
async def open_workflow_recovery_scanner(
    scanner_settings: Settings = settings,
) -> AsyncIterator[WorkflowRecoveryScanner]:
    """Compose only PostgreSQL discovery and broker publication dependencies."""
    engine = create_async_engine(scanner_settings.DATABASE_URL, poolclass=NullPool)
    failed = False
    try:
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        yield WorkflowRecoveryScanner(
            session_factory,
            CeleryWorkflowDispatcher(celery_app),
            batch_size=scanner_settings.WORKFLOW_RECOVERY_BATCH_SIZE,
            redispatch_delay=timedelta(
                seconds=scanner_settings.WORKFLOW_RECOVERY_REDISPATCH_DELAY_SECONDS
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
