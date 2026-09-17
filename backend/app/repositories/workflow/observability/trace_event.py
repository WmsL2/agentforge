"""Append-only workflow trace-event persistence primitives."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow.observability.trace_event import (
    WorkflowTraceEvent as DBWorkflowTraceEvent,
)
from app.services.workflow.execution.observability.domain import TraceEvent
from app.services.workflow.execution.observability.serialization import serialize_trace_event_state


async def create_workflow_trace_event(
    db: AsyncSession, *, event: TraceEvent
) -> DBWorkflowTraceEvent:
    """Append a trace event without committing the transaction."""
    state = serialize_trace_event_state(event)
    db_event = DBWorkflowTraceEvent(
        id=event.id,
        run_id=event.run_id,
        step_id=event.step_id,
        **state,
    )
    db.add(db_event)
    await db.flush()
    await db.refresh(db_event)
    return db_event


async def list_workflow_trace_events(
    db: AsyncSession, run_id: UUID
) -> list[DBWorkflowTraceEvent]:
    """List one run's append-only events in stable history order."""
    result = await db.execute(
        select(DBWorkflowTraceEvent)
        .where(DBWorkflowTraceEvent.run_id == run_id)
        .order_by(DBWorkflowTraceEvent.created_at.asc(), DBWorkflowTraceEvent.id.asc())
    )
    return list(result.scalars().all())
