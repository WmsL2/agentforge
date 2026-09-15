"""Application-owned durable persistence for successful workflow nodes."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow.run.model import WorkflowRun as DBWorkflowRun
from app.repositories.workflow.approval import repository as approval_repo
from app.repositories.workflow.checkpoint import repository as checkpoint_repo
from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.execution.approval import ApprovalRequest
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
        approval = _approval_from_interrupt(
            run,
            pending_node_id=pending_node_id,
            interrupt=interrupt,
        )
        await self._persist_checkpoint(
            run,
            completed_node_ids=completed_node_ids,
            pending_node_id=pending_node_id,
            interrupt=interrupt,
            approval=approval,
        )

    async def _persist_checkpoint(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str | None,
        interrupt: Mapping[str, Any] | None,
        approval: ApprovalRequest | None = None,
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
        if approval is not None:
            await approval_repo.create_approval_request(self._db, approval=approval)
        await self._db.commit()
        self._next_sequence += 1


def _approval_from_interrupt(
    run: WorkflowRun,
    *,
    pending_node_id: str,
    interrupt: Mapping[str, Any],
) -> ApprovalRequest | None:
    if interrupt.get("type") != "approval_required":
        return None
    payload = interrupt.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("Approval interrupt payload must be a mapping.")
    node_id = payload.get("node_id")
    prompt = payload.get("prompt")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("Approval interrupt payload node_id must be a non-blank string.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Approval interrupt payload prompt must be a non-blank string.")
    if node_id != pending_node_id:
        raise ValueError("Approval interrupt payload node_id must match pending node ID.")
    return ApprovalRequest(
        id=uuid4(),
        run_id=run.id,
        workflow_revision=run.workflow_revision,
        node_id=node_id,
        prompt=prompt,
    )
