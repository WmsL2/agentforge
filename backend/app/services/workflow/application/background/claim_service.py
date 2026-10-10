"""Application-owned short transactions for workflow execution leases."""

import math
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.workflow.run import claim as claim_repo
from app.services.workflow.application.background.domain import WorkflowExecutionLease


class WorkflowExecutionClaimService:
    """Own each claim operation's transaction on a dedicated idle session.

    ``AsyncSession.begin()`` commits on success and rolls back on exceptions,
    including cancellation. An already active caller transaction is rejected;
    unrelated caller writes must not be committed by this service. Fencing is
    separately available in the repository for caller-owned write transactions.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def claim(self, run_id: UUID, lease_duration: timedelta) -> WorkflowExecutionLease | None:
        _validate_duration(lease_duration)
        async with self._db.begin():
            return await claim_repo.claim_execution(self._db, run_id, lease_duration)

    async def renew(
        self, lease: WorkflowExecutionLease, lease_duration: timedelta
    ) -> WorkflowExecutionLease | None:
        _validate_duration(lease_duration)
        async with self._db.begin():
            return await claim_repo.renew_execution(self._db, lease, lease_duration)

    async def release(self, lease: WorkflowExecutionLease) -> bool:
        async with self._db.begin():
            return await claim_repo.release_execution(self._db, lease)


def _validate_duration(lease_duration: timedelta) -> None:
    if (
        not isinstance(lease_duration, timedelta)
        or not math.isfinite(lease_duration.total_seconds())
        or lease_duration <= timedelta(0)
    ):
        raise ValueError("lease_duration must be a finite, strictly positive timedelta.")
