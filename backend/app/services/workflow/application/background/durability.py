"""Short, fenced background persistence transactions."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.workflow.approval import repository as approval_repo
from app.repositories.workflow.checkpoint import repository as checkpoint_repo
from app.repositories.workflow.run import claim as claim_repo
from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.application.background.domain import (
    BackgroundRunStateError,
    WorkflowCheckpointSequenceError,
    WorkflowExecutionLease,
    WorkflowExecutionLeaseLostError,
)
from app.services.workflow.application.run.durability import _approval_from_interrupt
from app.services.workflow.execution.checkpoint import WorkflowCheckpoint
from app.services.workflow.execution.run.domain import WorkflowRun, WorkflowRunStatus


class FencedDurableWorkflowExecutionPersistence:
    """Fence and atomically persist each node, never holding a session across nodes."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        lease: WorkflowExecutionLease,
        *,
        next_sequence: int = 1,
    ) -> None:
        if next_sequence < 1:
            raise ValueError("next_sequence must be at least 1.")
        self._session_factory = session_factory
        self._lease = lease
        self._next_sequence = next_sequence
        self._persisted_status: WorkflowRunStatus | None = None

    @property
    def persisted_status(self) -> WorkflowRunStatus | None:
        """State whose transaction has actually committed in this attempt."""
        return self._persisted_status

    async def persist_node_completion(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str | None,
    ) -> None:
        if run.status not in (WorkflowRunStatus.RUNNING, WorkflowRunStatus.COMPLETED):
            raise BackgroundRunStateError("Node completion requires RUNNING or COMPLETED.")
        checkpoint = self._checkpoint(run, completed_node_ids, pending_node_id, None)
        await self._persist(run, checkpoint=checkpoint)

    async def persist_interruption(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str,
        interrupt: Mapping[str, Any],
    ) -> None:
        if run.status is not WorkflowRunStatus.PAUSED:
            raise BackgroundRunStateError("Interruption requires PAUSED.")
        checkpoint = self._checkpoint(run, completed_node_ids, pending_node_id, interrupt)
        await self._persist(run, checkpoint=checkpoint)

    async def persist_failure(self, run: WorkflowRun) -> None:
        """Commit FAILED state without inventing a successful-node checkpoint."""
        if run.status is not WorkflowRunStatus.FAILED:
            raise BackgroundRunStateError("Failure persistence requires FAILED.")
        await self._persist(run, checkpoint=None)

    def _checkpoint(
        self,
        run: WorkflowRun,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str | None,
        interrupt: Mapping[str, Any] | None,
    ) -> WorkflowCheckpoint:
        return WorkflowCheckpoint(
            id=uuid4(),
            run_id=run.id,
            workflow_revision=run.workflow_revision,
            sequence=self._next_sequence,
            completed_node_ids=completed_node_ids,
            node_outputs=run.node_outputs,
            pending_node_id=pending_node_id,
            interrupt=interrupt,
        )

    async def _persist(self, run: WorkflowRun, *, checkpoint: WorkflowCheckpoint | None) -> None:
        if run.id != self._lease.run_id:
            raise BackgroundRunStateError("Run does not match the execution lease.")
        async with self._session_factory() as db, db.begin():
            if not await claim_repo.lock_and_validate_execution_lease(db, self._lease):
                raise WorkflowExecutionLeaseLostError("Execution lease is no longer valid.")
            latest = await checkpoint_repo.get_latest_workflow_checkpoint(db, run.id)
            expected = 1 if latest is None else latest.sequence + 1
            if self._next_sequence != expected:
                raise WorkflowCheckpointSequenceError(
                    "Checkpoint sequence does not append to the latest commit."
                )
            if latest is not None and latest.workflow_revision != run.workflow_revision:
                raise BackgroundRunStateError("Latest checkpoint revision differs from the run.")
            db_run = await run_repo.get_workflow_run_by_id(db, run.id)
            if db_run is None or db_run.status not in ("pending", "running"):
                raise BackgroundRunStateError("Run is no longer in an executable state.")
            if (db_run.workflow_id, db_run.workflow_revision) != (
                run.workflow_id,
                run.workflow_revision,
            ):
                raise BackgroundRunStateError("Run identity or revision changed.")
            await run_repo.update_workflow_run_state(db, db_run=db_run, run=run)
            if checkpoint is not None:
                await checkpoint_repo.create_workflow_checkpoint(db, checkpoint=checkpoint)
                if checkpoint.interrupt is not None:
                    approval = _approval_from_interrupt(
                        run,
                        pending_node_id=checkpoint.pending_node_id,
                        interrupt=checkpoint.interrupt,
                    )
                    if approval is not None:
                        await approval_repo.create_approval_request(db, approval=approval)
        # Both the transaction and session must exit successfully before advancing.
        if checkpoint is not None:
            self._next_sequence += 1
        self._persisted_status = run.status
