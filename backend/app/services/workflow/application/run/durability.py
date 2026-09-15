"""Application-owned durable persistence for successful workflow nodes."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow.run.model import WorkflowRun as DBWorkflowRun
from app.repositories.workflow.checkpoint import repository as checkpoint_repo
from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.execution.checkpoint import WorkflowCheckpoint
from app.services.workflow.execution.run.domain import WorkflowRun


class DurableWorkflowExecutionPersistence:
    """Commit each successful node's run state and recovery checkpoint together."""

    def __init__(self, db: AsyncSession, db_run: DBWorkflowRun, *, next_sequence: int = 1):
        self._db = db
        self._db_run = db_run
        self._next_sequence = next_sequence

    async def persist_node_completion(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str | None,
    ) -> None:
        await self._persist_checkpoint(
            run,
            completed_node_ids=completed_node_ids,
            pending_node_id=pending_node_id,
            interrupt=None,
        )

    async def persist_interruption(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str,
        interrupt: Mapping[str, Any],
    ) -> None:
        await self._persist_checkpoint(
            run,
            completed_node_ids=completed_node_ids,
            pending_node_id=pending_node_id,
            interrupt=interrupt,
        )

    async def _persist_checkpoint(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str | None,
        interrupt: Mapping[str, Any] | None,
    ) -> None:
        checkpoint = WorkflowCheckpoint(
            id=uuid4(),
            run_id=run.id,
            workflow_revision=run.workflow_revision,
            sequence=self._next_sequence,
            completed_node_ids=completed_node_ids,
            node_outputs=run.node_outputs,
            pending_node_id=pending_node_id,
            interrupt=interrupt,
        )
        await run_repo.update_workflow_run_state(self._db, db_run=self._db_run, run=run)
        await checkpoint_repo.create_workflow_checkpoint(self._db, checkpoint=checkpoint)
        await self._db.commit()
        self._next_sequence += 1
