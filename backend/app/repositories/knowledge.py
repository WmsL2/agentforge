"""Knowledge base persistence primitives without transaction ownership."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import KnowledgeBase


async def create(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    name: str,
    description: str | None,
    created_by_user_id: UUID | None,
) -> KnowledgeBase:
    knowledge_base = KnowledgeBase(
        workspace_id=workspace_id,
        name=name,
        description=description,
        created_by_user_id=created_by_user_id,
    )
    db.add(knowledge_base)
    await db.flush()
    await db.refresh(knowledge_base)
    return knowledge_base


async def get_by_workspace_and_id(
    db: AsyncSession, *, workspace_id: UUID, knowledge_base_id: UUID
) -> KnowledgeBase | None:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.workspace_id == workspace_id,
            KnowledgeBase.id == knowledge_base_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_workspace_and_name(
    db: AsyncSession, *, workspace_id: UUID, name: str
) -> KnowledgeBase | None:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.workspace_id == workspace_id,
            KnowledgeBase.name == name,
        )
    )
    return result.scalar_one_or_none()


async def list_by_workspace(
    db: AsyncSession, *, workspace_id: UUID, skip: int, limit: int
) -> list[KnowledgeBase]:
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.workspace_id == workspace_id)
        .order_by(KnowledgeBase.created_at.asc(), KnowledgeBase.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_by_workspace(db: AsyncSession, *, workspace_id: UUID) -> int:
    result = await db.scalar(
        select(func.count())
        .select_from(KnowledgeBase)
        .where(KnowledgeBase.workspace_id == workspace_id)
    )
    return result or 0


async def update(
    db: AsyncSession, *, db_knowledge_base: KnowledgeBase, update_data: dict[str, Any]
) -> KnowledgeBase:
    for field, value in update_data.items():
        setattr(db_knowledge_base, field, value)
    db.add(db_knowledge_base)
    await db.flush()
    await db.refresh(db_knowledge_base)
    return db_knowledge_base


async def delete(db: AsyncSession, *, db_knowledge_base: KnowledgeBase) -> None:
    await db.delete(db_knowledge_base)
    await db.flush()
