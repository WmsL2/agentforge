"""Approval decisions that safely continue or cancel paused workflow runs."""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundError
from app.repositories.workflow.approval import repository as approval_repo
from app.repositories.workflow.checkpoint import repository as checkpoint_repo
from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.application.definition.service import WorkflowService
from app.services.workflow.application.run.durability import DurableWorkflowExecutionPersistence
from app.services.workflow.definition.serialization import deserialize_workflow_graph
from app.services.workflow.execution.approval import deserialize_approval_request
from app.services.workflow.execution.checkpoint import deserialize_workflow_checkpoint
from app.services.workflow.execution.engine import WorkflowEngine
from app.services.workflow.execution.run import WorkflowRunStatus, deserialize_workflow_run


class WorkflowApprovalConflictError(AppException):
    status_code = 409
    code = "APPROVAL_CONFLICT"
    message = "Approval request cannot be decided."


class WorkflowApprovalService:
    def __init__(self, db: AsyncSession, workflow_service: WorkflowService, engine: WorkflowEngine):
        self.db, self.workflow_service, self.engine = db, workflow_service, engine

    async def get_pending_approval(self, workflow_id: UUID, run_id: UUID, user_id: UUID):
        await self._owned_run(workflow_id, run_id, user_id)
        approval = await approval_repo.get_pending_approval_by_run(self.db, run_id)
        if approval is None:
            raise NotFoundError(message="Pending approval request not found")
        return approval

    async def approve(
        self,
        workflow_id: UUID,
        run_id: UUID,
        approval_id: UUID,
        user_id: UUID,
        *,
        note: str | None = None,
    ):
        workflow, db_run = await self._owned_run(workflow_id, run_id, user_id)
        db_approval, approval = await self._locked_pending(db_run, approval_id, run_id)
        run, definition, checkpoint = await self._state(workflow, db_run, approval)
        approval.approve(decided_by=user_id, note=note)
        resolved = _resolved(definition, checkpoint, approval)
        try:
            self.engine.validate_resume(definition, run, resolved)
        except ValueError as exc:
            raise _invalid(exc) from exc
        run.node_outputs = dict(resolved.node_outputs)
        updated = await approval_repo.update_approval_request_state(
            self.db, db_approval=db_approval, approval=approval
        )
        persistence = DurableWorkflowExecutionPersistence(
            self.db, db_run, next_sequence=checkpoint.sequence + 1
        )
        await persistence.persist_node_completion(
            run, completed_node_ids=resolved.completed_node_ids, pending_node_id=None
        )
        latest = await checkpoint_repo.get_latest_workflow_checkpoint(self.db, run.id)
        if latest is None or latest.sequence < resolved.sequence:
            raise _invalid("Approval completion checkpoint was not persisted.")
        await self.engine.resume(definition, run, _checkpoint(latest), persistence=persistence)
        if run.status is WorkflowRunStatus.FAILED:
            await run_repo.update_workflow_run_state(self.db, db_run=db_run, run=run)
            await self.db.commit()
        return updated

    async def reject(
        self,
        workflow_id: UUID,
        run_id: UUID,
        approval_id: UUID,
        user_id: UUID,
        *,
        note: str | None = None,
    ):
        workflow, db_run = await self._owned_run(workflow_id, run_id, user_id)
        db_approval, approval = await self._locked_pending(db_run, approval_id, run_id)
        run, _, _ = await self._state(workflow, db_run, approval)
        approval.reject(decided_by=user_id, note=note)
        run.cancel()
        updated = await approval_repo.update_approval_request_state(
            self.db, db_approval=db_approval, approval=approval
        )
        await run_repo.update_workflow_run_state(self.db, db_run=db_run, run=run)
        await self.db.commit()
        return updated

    async def _owned_run(self, workflow_id, run_id, user_id):
        workflow = await self.workflow_service.get_owned_workflow(workflow_id, user_id)
        db_run = await run_repo.get_workflow_run_by_id(self.db, run_id)
        if db_run is None or db_run.workflow_id != workflow_id:
            raise NotFoundError(message="Workflow run not found")
        return workflow, db_run

    async def _locked_pending(self, db_run, approval_id, run_id):
        row = await approval_repo.get_approval_request_by_id_for_update(self.db, approval_id)
        if row is None or row.run_id != run_id:
            raise NotFoundError(message="Approval request not found")
        approval = _approval(row)
        if approval.status.value != "pending":
            raise WorkflowApprovalConflictError(
                message="Approval request has already been decided.",
                code="APPROVAL_ALREADY_DECIDED",
            )
        if db_run.status != WorkflowRunStatus.PAUSED.value:
            raise WorkflowApprovalConflictError(
                message="Workflow run must be paused before deciding approval.",
                code="WORKFLOW_RUN_NOT_PAUSED",
            )
        return row, approval

    async def _state(self, workflow, db_run, approval):
        run = _run(db_run)
        definition = deserialize_workflow_graph(
            db_run.definition_snapshot,
            workflow_id=db_run.workflow_id,
            name=workflow.name,
            description=workflow.description,
            revision=db_run.workflow_revision,
        )
        row = await checkpoint_repo.get_latest_workflow_checkpoint(self.db, run.id)
        if row is None:
            raise WorkflowApprovalConflictError(
                message="Workflow checkpoint not found.", code="WORKFLOW_CHECKPOINT_NOT_FOUND"
            )
        checkpoint = _checkpoint(row)
        try:
            _validate(definition, run, checkpoint, approval)
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid(exc) from exc
        return run, definition, checkpoint


def _run(row):
    return deserialize_workflow_run(
        run_id=row.id,
        workflow_id=row.workflow_id,
        workflow_revision=row.workflow_revision,
        status=row.status,
        input=row.input,
        node_outputs=row.node_outputs,
        output=row.output,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _checkpoint(row):
    return deserialize_workflow_checkpoint(
        checkpoint_id=row.id,
        run_id=row.run_id,
        workflow_revision=row.workflow_revision,
        sequence=row.sequence,
        completed_node_ids=row.completed_node_ids,
        node_outputs=row.node_outputs,
        pending_node_id=row.pending_node_id,
        interrupt=row.interrupt,
        created_at=row.created_at,
    )


def _approval(row):
    return deserialize_approval_request(
        {
            "id": row.id,
            "run_id": row.run_id,
            "workflow_revision": row.workflow_revision,
            "node_id": row.node_id,
            "prompt": row.prompt,
            "status": row.status,
            "created_at": row.created_at,
            "decided_at": row.decided_at,
            "decided_by": row.decided_by,
            "decision_note": row.decision_note,
        }
    )


def _validate(definition, run, checkpoint, approval):
    if (
        checkpoint.run_id != run.id
        or checkpoint.workflow_revision != run.workflow_revision
        or approval.workflow_revision != run.workflow_revision
    ):
        raise ValueError("Revision mismatch.")
    interrupt = checkpoint.interrupt
    if (
        checkpoint.pending_node_id != approval.node_id
        or not isinstance(interrupt, Mapping)
        or interrupt.get("type") != "approval_required"
    ):
        raise ValueError("Pending approval interruption mismatch.")
    payload = interrupt.get("payload")
    if (
        not isinstance(payload, Mapping)
        or payload.get("node_id") != approval.node_id
        or payload.get("prompt") != approval.prompt
    ):
        raise ValueError("Approval payload mismatch.")
    node = next((n for n in definition.nodes if n.id == approval.node_id), None)
    if node is None or node.kind.value != "approval":
        raise ValueError("Approval node mismatch.")


def _resolved(definition, checkpoint, approval):
    completed = set(checkpoint.completed_node_ids)
    completed.add(approval.node_id)
    outputs = dict(checkpoint.node_outputs)
    outputs[approval.node_id] = {
        "decision": "approved",
        "approval_id": str(approval.id),
        "decided_by": str(approval.decided_by),
        "decided_at": approval.decided_at.isoformat(),
        "decision_note": approval.decision_note,
    }
    from uuid import UUID as Uuid

    from app.services.workflow.execution.checkpoint import WorkflowCheckpoint

    return WorkflowCheckpoint(
        id=Uuid(int=0),
        run_id=checkpoint.run_id,
        workflow_revision=checkpoint.workflow_revision,
        sequence=checkpoint.sequence + 1,
        completed_node_ids=tuple(n.id for n in definition.nodes if n.id in completed),
        node_outputs=outputs,
        pending_node_id=None,
        interrupt=None,
    )


def _invalid(reason):
    return WorkflowApprovalConflictError(
        message=f"Approval resume state is invalid: {reason}", code="APPROVAL_RESUME_STATE_INVALID"
    )
