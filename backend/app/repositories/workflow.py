"""Workflow aggregate persistence operations."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow import Workflow


async def get_workflow_by_id(db: AsyncSession, workflow_id: UUID) -> Workflow | None:
    return await db.get(Workflow, workflow_id)


async def create_workflow(
    db: AsyncSession,
    *,
    workflow_id: UUID,
    user_id: UUID,
    name: str,
    description: str | None,
    definition: dict[str, Any],
    revision: int = 1,
) -> Workflow:
    workflow = Workflow(
        id=workflow_id,
        user_id=user_id,
        name=name,
        description=description,
        definition=definition,
        revision=revision,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return workflow


async def list_workflows_by_user(
    db: AsyncSession, user_id: UUID, *, skip: int = 0, limit: int = 50
) -> list[Workflow]:
    result = await db.execute(
        select(Workflow)
        .where(Workflow.user_id == user_id)
        .order_by(Workflow.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_workflows_by_user(db: AsyncSession, user_id: UUID) -> int:
    return (
        await db.scalar(select(func.count(Workflow.id)).where(Workflow.user_id == user_id))
    ) or 0


async def update_workflow(
    db: AsyncSession, *, db_workflow: Workflow, update_data: dict[str, Any]
) -> Workflow:
    for field, value in update_data.items():
        setattr(db_workflow, field, value)
    db.add(db_workflow)
    await db.flush()
    await db.refresh(db_workflow)
    return db_workflow


async def delete_workflow(db: AsyncSession, workflow_id: UUID) -> bool:
    workflow = await get_workflow_by_id(db, workflow_id)
    if workflow is None:
        return False
    await db.delete(workflow)
    await db.flush()
    return True
