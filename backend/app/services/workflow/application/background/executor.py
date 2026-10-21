"""Background workflow coordination without a queue or HTTP composition entry point."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.workflow.checkpoint import repository as checkpoint_repo
from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.application.background.claim_service import WorkflowExecutionClaimService
from app.services.workflow.application.background.domain import (
    BackgroundRunExecutionResult,
    BackgroundRunExecutionStatus,
    BackgroundRunStateError,
    WorkflowExecutionJob,
    WorkflowExecutionLease,
    WorkflowExecutionLeaseLostError,
)
from app.services.workflow.application.background.durability import (
    FencedDurableWorkflowExecutionPersistence,
)
from app.services.workflow.definition.model.domain import WorkflowDefinition
from app.services.workflow.definition.serialization.serializer import deserialize_workflow_graph
from app.services.workflow.execution.checkpoint import (
    WorkflowCheckpoint,
    deserialize_workflow_checkpoint,
)
from app.services.workflow.execution.engine import WorkflowEngine
from app.services.workflow.execution.run import deserialize_workflow_run
from app.services.workflow.execution.run.domain import WorkflowRun, WorkflowRunStatus


class BackgroundRunExecutor:
    """Use independent sessions for claim, reading, each write, and safe release.

    Infrastructure errors and cancellation propagate, retaining the lease for
    later expired-lease recovery. Only successfully persisted terminal/pause
    outcomes permit best-effort release. There is no automatic heartbeat.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        engine: WorkflowEngine,
        *,
        lease_duration: timedelta,
    ) -> None:
        self._session_factory = session_factory
        self._engine = engine
        self._lease_duration = lease_duration

    async def execute(self, job: WorkflowExecutionJob) -> BackgroundRunExecutionResult:
        async with self._session_factory() as db:
            lease = await WorkflowExecutionClaimService(db).claim(job.run_id, self._lease_duration)
        if lease is None:
            return BackgroundRunExecutionResult(
                job.run_id, BackgroundRunExecutionStatus.NOT_CLAIMED
            )
        return await self.execute_claimed(job, lease)

    async def execute_claimed(
        self, job: WorkflowExecutionJob, lease: WorkflowExecutionLease
    ) -> BackgroundRunExecutionResult:
        """Execute an already committed claim through the normal fenced path."""
        if job.run_id != lease.run_id:
            raise BackgroundRunStateError("Claimed lease does not match the execution job.")

        try:
            definition, run, checkpoint = await self._load(lease)
            persistence = FencedDurableWorkflowExecutionPersistence(
                self._session_factory,
                lease,
                next_sequence=1 if checkpoint is None else checkpoint.sequence + 1,
            )
            if run.status is WorkflowRunStatus.PENDING:
                if checkpoint is not None:
                    raise BackgroundRunStateError("PENDING run already has a checkpoint.")
                await self._engine.execute(definition, run, persistence=persistence)
            elif run.status is WorkflowRunStatus.RUNNING:
                if checkpoint is None:
                    raise BackgroundRunStateError("RUNNING recovery requires a checkpoint.")
                await self._engine.recover_running(
                    definition, run, checkpoint, persistence=persistence
                )
            else:
                raise BackgroundRunStateError("Claimed run is not PENDING or RUNNING.")
            if run.status is WorkflowRunStatus.FAILED:
                await persistence.persist_failure(run)
            if run.status not in (
                WorkflowRunStatus.COMPLETED,
                WorkflowRunStatus.PAUSED,
                WorkflowRunStatus.FAILED,
            ):
                raise BackgroundRunStateError("Engine did not produce a terminal or paused result.")
            if persistence.persisted_status is not run.status:
                raise BackgroundRunStateError("Engine result was not durably committed.")
        except WorkflowExecutionLeaseLostError:
            return BackgroundRunExecutionResult(job.run_id, BackgroundRunExecutionStatus.LEASE_LOST)

        # Never release on invalid state, infrastructure errors, or cancellation.
        try:
            async with self._session_factory() as db:
                released = await WorkflowExecutionClaimService(db).release(lease)
        except Exception as error:
            return BackgroundRunExecutionResult(
                job.run_id,
                BackgroundRunExecutionStatus(run.status.value),
                release_error=f"{type(error).__name__}: {error}",
            )
        return BackgroundRunExecutionResult(
            job.run_id, BackgroundRunExecutionStatus(run.status.value), lease_released=released
        )

    async def _load(
        self, lease: WorkflowExecutionLease
    ) -> tuple[WorkflowDefinition, WorkflowRun, WorkflowCheckpoint | None]:
        async with self._session_factory() as db, db.begin():
            row = await run_repo.get_workflow_run_by_id(db, lease.run_id)
            if row is None:
                raise BackgroundRunStateError("Claimed run is missing.")
            if (row.execution_claim_token, row.execution_claim_generation) != (
                lease.claim_token,
                lease.generation,
            ):
                raise WorkflowExecutionLeaseLostError(
                    "Claim changed before loading execution state."
                )
            now = await db.scalar(select(func.clock_timestamp()))
            if row.execution_lease_expires_at is None or row.execution_lease_expires_at <= now:
                raise WorkflowExecutionLeaseLostError(
                    "Lease expired before execution state was loaded."
                )
            run = deserialize_workflow_run(
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
            definition = deserialize_workflow_graph(
                row.definition_snapshot,
                workflow_id=row.workflow_id,
                name="Persisted workflow run",
                description=None,
                revision=row.workflow_revision,
            )
            stored = await checkpoint_repo.get_latest_workflow_checkpoint(db, row.id)
            checkpoint = (
                None
                if stored is None
                else deserialize_workflow_checkpoint(
                    checkpoint_id=stored.id,
                    run_id=stored.run_id,
                    workflow_revision=stored.workflow_revision,
                    sequence=stored.sequence,
                    completed_node_ids=stored.completed_node_ids,
                    node_outputs=stored.node_outputs,
                    pending_node_id=stored.pending_node_id,
                    interrupt=stored.interrupt,
                    created_at=stored.created_at,
                )
            )
            return definition, run, checkpoint
