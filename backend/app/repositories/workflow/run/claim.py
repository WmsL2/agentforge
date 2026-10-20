"""PostgreSQL execution ownership primitives; the caller owns the transaction."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, case, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow.approval.model import ApprovalRequest
from app.db.models.workflow.checkpoint.model import WorkflowCheckpoint
from app.db.models.workflow.run.model import WorkflowRun
from app.services.workflow.application.background.domain import WorkflowExecutionLease


def _lease_columns():
    return (
        WorkflowRun.id.label("run_id"),
        WorkflowRun.execution_claim_token.label("claim_token"),
        WorkflowRun.execution_claim_generation.label("generation"),
        WorkflowRun.execution_lease_expires_at.label("expires_at"),
    )


def _valid_lease(lease: WorkflowExecutionLease):
    return and_(
        WorkflowRun.id == lease.run_id,
        WorkflowRun.execution_claim_token == lease.claim_token,
        WorkflowRun.execution_claim_generation == lease.generation,
        WorkflowRun.execution_lease_expires_at > func.clock_timestamp(),
    )


async def claim_execution(
    db: AsyncSession, run_id: UUID, lease_duration: timedelta
) -> WorkflowExecutionLease | None:
    """Atomically claim an eligible run, without changing its business status."""
    expired = and_(
        WorkflowRun.execution_claim_token.is_not(None),
        WorkflowRun.execution_lease_expires_at <= func.clock_timestamp(),
    )
    eligible = or_(
        and_(
            WorkflowRun.status == "pending",
            or_(WorkflowRun.execution_claim_token.is_(None), expired),
        ),
        and_(WorkflowRun.status == "running", expired),
        _approved_paused_recovery_candidate(expired),
    )
    result = await db.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run_id, eligible)
        .values(
            status=case((WorkflowRun.status == "paused", "running"), else_=WorkflowRun.status),
            execution_claim_token=uuid4(),
            execution_claim_generation=WorkflowRun.execution_claim_generation + 1,
            execution_lease_expires_at=func.clock_timestamp() + lease_duration,
        )
        .returning(*_lease_columns())
        .execution_options(synchronize_session=False)
    )
    row = result.mappings().one_or_none()
    return WorkflowExecutionLease(**row) if row is not None else None


def _approved_paused_recovery_candidate(expired):
    """Return the narrowly-scoped PAUSED resume predicate.

    A decision is recoverable only after an APPROVED approval and its later
    resolution checkpoint have both committed.  This deliberately does not
    make arbitrary lease-free PAUSED rows executable.
    """
    latest_checkpoint_id = (
        select(WorkflowCheckpoint.id)
        .where(WorkflowCheckpoint.run_id == WorkflowRun.id)
        .order_by(WorkflowCheckpoint.sequence.desc())
        .limit(1)
        .correlate(WorkflowRun)
        .scalar_subquery()
    )
    approved_resolution = exists(
        select(WorkflowCheckpoint.id)
        .join(ApprovalRequest, ApprovalRequest.run_id == WorkflowCheckpoint.run_id)
        .where(
            WorkflowCheckpoint.run_id == WorkflowRun.id,
            WorkflowCheckpoint.id == latest_checkpoint_id,
            WorkflowCheckpoint.pending_node_id.is_(None),
            WorkflowCheckpoint.interrupt.is_(None),
            ApprovalRequest.status == "approved",
            ApprovalRequest.workflow_revision == WorkflowRun.workflow_revision,
            WorkflowCheckpoint.workflow_revision == WorkflowRun.workflow_revision,
            WorkflowCheckpoint.completed_node_ids.has_key(ApprovalRequest.node_id),
        )
    )
    return and_(
        WorkflowRun.status == "paused",
        or_(WorkflowRun.execution_claim_token.is_(None), expired),
        approved_resolution,
    )


def recoverable_execution_condition():
    """Candidate predicate shared by recovery scanning and atomic claiming."""
    expired = and_(
        WorkflowRun.execution_claim_token.is_not(None),
        WorkflowRun.execution_lease_expires_at <= func.clock_timestamp(),
    )
    return or_(
        and_(
            WorkflowRun.status == "pending",
            or_(WorkflowRun.execution_claim_token.is_(None), expired),
        ),
        and_(WorkflowRun.status == "running", expired),
        _approved_paused_recovery_candidate(expired),
    )


async def renew_execution(
    db: AsyncSession, lease: WorkflowExecutionLease, lease_duration: timedelta
) -> WorkflowExecutionLease | None:
    """Renew only matching, unexpired database credentials."""
    result = await db.execute(
        update(WorkflowRun)
        .where(_valid_lease(lease))
        .values(execution_lease_expires_at=func.clock_timestamp() + lease_duration)
        .returning(*_lease_columns())
        .execution_options(synchronize_session=False)
    )
    row = result.mappings().one_or_none()
    return WorkflowExecutionLease(**row) if row is not None else None


async def release_execution(db: AsyncSession, lease: WorkflowExecutionLease) -> bool:
    """Clear an unexpired lease while preserving its generation."""
    result = await db.execute(
        update(WorkflowRun)
        .where(_valid_lease(lease))
        .values(execution_claim_token=None, execution_lease_expires_at=None)
        .returning(WorkflowRun.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


async def lock_and_validate_execution_lease(
    db: AsyncSession, lease: WorkflowExecutionLease
) -> bool:
    """Hold a run's row lock for the caller's protected writes and transaction.

    Check the database clock *after* acquiring the lock: a lease may expire
    while this transaction waits. Never commit, roll back, or release here.
    """
    run_id = await db.scalar(
        select(WorkflowRun.id).where(WorkflowRun.id == lease.run_id).with_for_update()
    )
    if run_id is None:
        return False
    return await db.scalar(select(WorkflowRun.id).where(_valid_lease(lease))) is not None
