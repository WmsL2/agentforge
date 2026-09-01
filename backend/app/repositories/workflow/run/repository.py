"""Workflow-run database read and state-update primitives."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow.run.model import WorkflowRun as DBWorkflowRun
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
