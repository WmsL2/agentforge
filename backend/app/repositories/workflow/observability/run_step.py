"""Workflow run-step database primitives without transaction ownership."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow.observability.run_step import WorkflowRunStep as DBWorkflowRunStep
from app.services.workflow.execution.observability.domain import RunStep
from app.services.workflow.execution.observability.serialization import serialize_run_step_state


async def create_workflow_run_step(db: AsyncSession, *, step: RunStep) -> DBWorkflowRunStep:
    """Persist a new actual execution attempt without committing the transaction."""
    state = serialize_run_step_state(step)
    db_step = DBWorkflowRunStep(
        id=step.id,
        run_id=step.run_id,
        sequence=step.sequence,
        node_id=step.node_id,
        node_kind=step.node_kind.value,
        status=state["status"],
        input=state["input"],
        output=state["output"],
        error=state["error"],
        metadata_=state["metadata"],
        started_at=state["started_at"],
        finished_at=state["finished_at"],
    )
    db.add(db_step)
    await db.flush()
    await db.refresh(db_step)
    return db_step


async def update_workflow_run_step_state(
    db: AsyncSession,
    *,
    db_step: DBWorkflowRunStep,
    step: RunStep,
) -> DBWorkflowRunStep:
    """Persist only the mutable outcome fields of an existing execution attempt."""
    state = serialize_run_step_state(step)
    for field in ("status", "output", "error", "metadata", "finished_at"):
        setattr(db_step, "metadata_" if field == "metadata" else field, state[field])
    db.add(db_step)
    await db.flush()
    await db.refresh(db_step)
    return db_step


async def get_workflow_run_step_by_id(db: AsyncSession, step_id: UUID) -> DBWorkflowRunStep | None:
    """Return one run step by identity, if it exists."""
    return await db.get(DBWorkflowRunStep, step_id)


async def list_workflow_run_steps(db: AsyncSession, run_id: UUID) -> list[DBWorkflowRunStep]:
    """List one run's execution attempts in their provided sequence order."""
    result = await db.execute(
        select(DBWorkflowRunStep)
        .where(DBWorkflowRunStep.run_id == run_id)
        .order_by(DBWorkflowRunStep.sequence.asc())
    )
    return list(result.scalars().all())
