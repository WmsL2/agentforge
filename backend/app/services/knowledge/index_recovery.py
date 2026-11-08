"""Bounded recovery publication for pending and expired knowledge index jobs."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories import knowledge_index as index_repo
from app.services.knowledge.indexing_service import KnowledgeIndexDispatcher


@dataclass(frozen=True)
class IndexRecoveryResult:
    scanned: int
    dispatched: int
    failed: int


class KnowledgeIndexRecoveryScanner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        dispatcher: KnowledgeIndexDispatcher,
        *,
        batch_size: int,
        redispatch_delay: timedelta,
    ) -> None:
        if batch_size <= 0 or redispatch_delay <= timedelta(0):
            raise ValueError("recovery limits must be positive")
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._batch_size = batch_size
        self._redispatch_delay = redispatch_delay

    async def scan_once(self) -> IndexRecoveryResult:
        async with self._session_factory() as db, db.begin():
            job_ids = await index_repo.list_recoverable_job_ids(
                db, limit=self._batch_size, redispatch_delay=self._redispatch_delay
            )
        dispatched = failed = 0
        for job_id in job_ids:
            try:
                await self._dispatcher.dispatch(job_id)
            except Exception:
                failed += 1
            else:
                dispatched += 1
        return IndexRecoveryResult(len(job_ids), dispatched, failed)
