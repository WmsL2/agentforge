"""Approval-request database primitives without transaction ownership."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow.approval.model import ApprovalRequest as DBApprovalRequest
from app.services.workflow.execution.approval.domain import ApprovalRequest
from app.services.workflow.execution.approval.serialization import serialize_approval_request


async def create_approval_request(
    db: AsyncSession, *, approval: ApprovalRequest
) -> DBApprovalRequest:
    db_approval = DBApprovalRequest(
        id=approval.id,
        run_id=approval.run_id,
        workflow_revision=approval.workflow_revision,
        node_id=approval.node_id,
        prompt=approval.prompt,
        **serialize_approval_request(approval),
    )
    db.add(db_approval)
    await db.flush()
    await db.refresh(db_approval)
    return db_approval


async def get_approval_request_by_id(
    db: AsyncSession, approval_id: UUID
) -> DBApprovalRequest | None:
    return await db.get(DBApprovalRequest, approval_id)


async def get_approval_request_by_id_for_update(
    db: AsyncSession, approval_id: UUID
) -> DBApprovalRequest | None:
    """Read one approval request while serializing its decision transaction."""
    result = await db.execute(
        select(DBApprovalRequest)
        .where(DBApprovalRequest.id == approval_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def get_pending_approval_by_run(
    db: AsyncSession, run_id: UUID
) -> DBApprovalRequest | None:
    result = await db.execute(
        select(DBApprovalRequest)
        .where(
            DBApprovalRequest.run_id == run_id,
            DBApprovalRequest.status == "pending",
        )
        .order_by(DBApprovalRequest.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_approval_request_state(
    db: AsyncSession,
    *,
    db_approval: DBApprovalRequest,
    approval: ApprovalRequest,
) -> DBApprovalRequest:
    for field, value in serialize_approval_request(approval).items():
        setattr(db_approval, field, value)
    db.add(db_approval)
    await db.flush()
    await db.refresh(db_approval)
    return db_approval
