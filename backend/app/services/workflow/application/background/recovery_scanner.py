"""Bounded discovery and re-dispatch of durable workflow executions."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.application.background.contract import WorkflowExecutionDispatcher
from app.services.workflow.application.background.domain import WorkflowExecutionJob


@dataclass(frozen=True)
class RecoveryScanResult:
    """Observable outcome of one bounded scan; errors contain no payload data."""

    scanned: int
    dispatched: int
    skipped: int
    failed: int


class WorkflowRecoveryScanner:
    """Find recoverable rows in PostgreSQL, then publish after releasing locks.

    This is intentionally a dispatcher, not an executor.  PostgreSQL row locks
    plus ``SKIP LOCKED`` coordinate simultaneous scanners; the execution claim
    remains the final fencing authority when a broker redelivers a run ID.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        dispatcher: WorkflowExecutionDispatcher,
        *,
        batch_size: int,
        redispatch_delay: timedelta,
    ) -> None:
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
            raise ValueError("batch_size must be a strictly positive integer.")
        if not isinstance(redispatch_delay, timedelta) or redispatch_delay <= timedelta(0):
            raise ValueError("redispatch_delay must be a strictly positive timedelta.")
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._batch_size = batch_size
        self._redispatch_delay = redispatch_delay

    async def scan_once(self) -> RecoveryScanResult:
        async with self._session_factory() as db, db.begin():
            run_ids = await run_repo.list_recoverable_workflow_run_ids_for_update(
                db,
                limit=self._batch_size,
                redispatch_delay=self._redispatch_delay,
            )

        dispatched = failed = 0
        for run_id in run_ids:
            try:
                await self._dispatcher.dispatch(WorkflowExecutionJob(run_id))
            except Exception:
                # One unavailable broker must not prevent another candidate's
                # publication.  The row remains recoverable for the next scan.
                failed += 1
            else:
                dispatched += 1
        return RecoveryScanResult(
            scanned=len(run_ids), dispatched=dispatched, skipped=0, failed=failed
        )
