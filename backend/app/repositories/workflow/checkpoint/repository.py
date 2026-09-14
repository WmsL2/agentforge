"""Append-only workflow checkpoint persistence primitives."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow.checkpoint.model import WorkflowCheckpoint as DBWorkflowCheckpoint
from app.services.workflow.execution.checkpoint import WorkflowCheckpoint
from app.services.workflow.execution.checkpoint.serialization import (
    serialize_workflow_checkpoint_state,
)


async def create_workflow_checkpoint(
    db: AsyncSession,
    *,
    checkpoint: WorkflowCheckpoint,
) -> DBWorkflowCheckpoint:
    """Persist one immutable checkpoint without owning the transaction."""
    state = serialize_workflow_checkpoint_state(checkpoint)
    db_checkpoint = DBWorkflowCheckpoint(
        id=checkpoint.id,
        run_id=checkpoint.run_id,
        workflow_revision=checkpoint.workflow_revision,
        sequence=checkpoint.sequence,
        **state,
    )
    db.add(db_checkpoint)
    await db.flush()
    await db.refresh(db_checkpoint)
    return db_checkpoint


async def get_latest_workflow_checkpoint(
    db: AsyncSession,
    run_id: UUID,
) -> DBWorkflowCheckpoint | None:
    """Return the newest checkpoint for one run, if it exists."""
    result = await db.execute(
        select(DBWorkflowCheckpoint)
        .where(DBWorkflowCheckpoint.run_id == run_id)
        .order_by(DBWorkflowCheckpoint.sequence.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
