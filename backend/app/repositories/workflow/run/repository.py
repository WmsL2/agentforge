"""Workflow-run database read and state-update primitives."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, nullsfirst, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow.run.model import WorkflowRun as DBWorkflowRun
from app.repositories.workflow.run.claim import recoverable_execution_condition
from app.services.workflow.execution.run.domain import WorkflowRun as DomainWorkflowRun
from app.services.workflow.execution.run.serialization.serializer import (
    serialize_workflow_run_state,
)


async def get_workflow_run_by_id(db: AsyncSession, run_id: UUID) -> DBWorkflowRun | None:
    return await db.get(DBWorkflowRun, run_id)


async def create_workflow_run(
    db: AsyncSession,
    *,
    run: DomainWorkflowRun,
    definition_snapshot: dict[str, Any],
) -> DBWorkflowRun:
    state = serialize_workflow_run_state(run)
    db_run = DBWorkflowRun(
        id=run.id,
        workflow_id=run.workflow_id,
        workflow_revision=run.workflow_revision,
        definition_snapshot=definition_snapshot,
        **state,
    )
    db.add(db_run)
    await db.flush()
    await db.refresh(db_run)
    return db_run


async def list_workflow_runs_by_workflow(
    db: AsyncSession,
    workflow_id: UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[DBWorkflowRun]:
    result = await db.execute(
        select(DBWorkflowRun)
        .where(DBWorkflowRun.workflow_id == workflow_id)
        .order_by(DBWorkflowRun.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_workflow_runs_by_workflow(db: AsyncSession, workflow_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count(DBWorkflowRun.id)).where(DBWorkflowRun.workflow_id == workflow_id)
        )
    ) or 0


async def list_recoverable_workflow_run_ids_for_update(
    db: AsyncSession, *, limit: int, redispatch_delay: timedelta
) -> list[UUID]:
    """Reserve one fair bounded batch of database-clock recovery candidates.

    Reservation makes a selected row ineligible until its next dispatch time,
    so a permanently recoverable early row cannot starve later candidates.
    The scanner still releases locks before publication. A later duplicate
    delivery is safe because execution must win its atomic database claim.
    """
    database_now = func.clock_timestamp()
    result = await db.execute(
        select(DBWorkflowRun.id)
        .where(
            recoverable_execution_condition(),
            or_(
                DBWorkflowRun.recovery_next_dispatch_at.is_(None),
                DBWorkflowRun.recovery_next_dispatch_at <= database_now,
            ),
        )
        .order_by(
            nullsfirst(DBWorkflowRun.recovery_last_dispatched_at.asc()),
            DBWorkflowRun.created_at.asc(),
            DBWorkflowRun.id.asc(),
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    run_ids = list(result.scalars())
    if run_ids:
        await db.execute(
            update(DBWorkflowRun)
            .where(DBWorkflowRun.id.in_(run_ids))
            .values(
                recovery_last_dispatched_at=database_now,
                recovery_next_dispatch_at=database_now + redispatch_delay,
            )
            .execution_options(synchronize_session=False)
        )
    return run_ids


async def update_workflow_run_state(
    db: AsyncSession,
    *,
    db_run: DBWorkflowRun,
    run: DomainWorkflowRun,
) -> DBWorkflowRun:
    state = serialize_workflow_run_state(run)
    for field in ("status", "node_outputs", "output", "error", "started_at", "finished_at"):
        setattr(db_run, field, state[field])
    db.add(db_run)
    await db.flush()
    await db.refresh(db_run)
    return db_run
