"""Background orchestration, snapshot restoration and safe release boundaries."""

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import workflow
from app.services.workflow import (
    ApprovalNodeExecutor,
    BackgroundRunExecutionResult,
    BackgroundRunExecutionStatus,
    BackgroundRunExecutor,
    BackgroundRunStateError,
    DeterministicNodeExecutor,
    WorkflowCheckpoint,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowExecutionJob,
    WorkflowExecutionLease,
    WorkflowExecutionLeaseLostError,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowRun,
    WorkflowRunStatus,
    serialize_workflow_graph,
)
from app.services.workflow.application.background import executor as module


@pytest.fixture
def setup(monkeypatch):
    definition = WorkflowDefinition(
        uuid4(),
        "Snapshot V1",
        "start",
        nodes=(
            WorkflowNode("start", WorkflowNodeKind.START),
            WorkflowNode("value", WorkflowNodeKind.VALUE, config={"value": "V1"}),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        edges=(WorkflowEdge("sv", "start", "value"), WorkflowEdge("ve", "value", "end")),
    )
    run = WorkflowRun(uuid4(), definition.id, 1)
    lease = WorkflowExecutionLease(run.id, uuid4(), 1, datetime(2030, 1, 1, tzinfo=UTC))
    factory = MagicMock()
    sessions = []

    def new_session():
        db = MagicMock(spec=AsyncSession)
        db.__aenter__.return_value = db
        sessions.append(db)
        return db

    factory.side_effect = new_session
    claim_service = MagicMock()
    claim_service.claim = AsyncMock(return_value=lease)
    claim_service.release = AsyncMock(return_value=True)
    monkeypatch.setattr(
        module, "WorkflowExecutionClaimService", MagicMock(return_value=claim_service)
    )
    persistence = MagicMock()
    persistence.persisted_status = None

    async def persist(current, **kwargs):
        persistence.persisted_status = current.status

    persistence.persist_node_completion = AsyncMock(side_effect=persist)
    persistence.persist_interruption = AsyncMock(side_effect=persist)
    persistence.persist_failure = AsyncMock(side_effect=persist)
    persistence_class = MagicMock(return_value=persistence)
    monkeypatch.setattr(module, "FencedDurableWorkflowExecutionPersistence", persistence_class)
    node_executor = AsyncMock(wraps=DeterministicNodeExecutor())
    engine = WorkflowEngine(node_executor)
    engine.execute = AsyncMock(wraps=engine.execute)
    engine.recover_running = AsyncMock(wraps=engine.recover_running)
    subject = BackgroundRunExecutor(factory, engine, lease_duration=timedelta(minutes=5))
    loader = AsyncMock(return_value=(definition, run, None))
    monkeypatch.setattr(subject, "_load", loader)
    return SimpleNamespace(
        subject=subject,
        loader=loader,
        run=run,
        definition=definition,
        lease=lease,
        factory=factory,
        sessions=sessions,
        claim_service=claim_service,
        engine=engine,
        nodes=node_executor,
        persistence=persistence,
        persistence_class=persistence_class,
        job=WorkflowExecutionJob(run.id),
    )


@pytest.mark.anyio
async def test_claim_then_execute_then_durable_completion_and_release(setup):
    result = await setup.subject.execute(setup.job)
    assert result.status is BackgroundRunExecutionStatus.COMPLETED and result.lease_released
    setup.engine.execute.assert_awaited_once()
    setup.engine.recover_running.assert_not_awaited()
    assert setup.persistence.persist_node_completion.await_count == 3
    setup.claim_service.release.assert_awaited_once_with(setup.lease)
    assert len(setup.sessions) == 2 and setup.sessions[0] is not setup.sessions[1]
    setup.sessions[0].__aexit__.assert_awaited_once()


@pytest.mark.anyio
async def test_rejected_claim_has_no_execution_reads_writes_or_release(setup):
    setup.claim_service.claim.return_value = None
    result = await setup.subject.execute(setup.job)
    assert result.status is BackgroundRunExecutionStatus.NOT_CLAIMED
    setup.loader.assert_not_awaited()
    setup.engine.execute.assert_not_awaited()
    setup.engine.recover_running.assert_not_awaited()
    setup.persistence_class.assert_not_called()
    setup.claim_service.release.assert_not_awaited()


@pytest.mark.anyio
async def test_running_uses_checkpoint_recovery_and_continues_sequence(setup):
    setup.run.start(at=datetime(2026, 1, 1, tzinfo=UTC))
    checkpoint = WorkflowCheckpoint(
        uuid4(), setup.run.id, 1, 7, ("start",), {"start": {}}, pending_node_id="value"
    )
    setup.loader.return_value = (setup.definition, setup.run, checkpoint)
    result = await setup.subject.execute(setup.job)
    assert result.status is BackgroundRunExecutionStatus.COMPLETED
    setup.engine.execute.assert_not_awaited()
    setup.engine.recover_running.assert_awaited_once()
    assert setup.persistence_class.call_args.kwargs["next_sequence"] == 8
    assert [call.args[0].id for call in setup.nodes.execute.await_args_list] == ["value", "end"]
    assert setup.run.started_at == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,with_checkpoint",
    [
        (WorkflowRunStatus.PENDING, True),
        (WorkflowRunStatus.RUNNING, False),
        (WorkflowRunStatus.PAUSED, False),
        (WorkflowRunStatus.COMPLETED, False),
        (WorkflowRunStatus.FAILED, False),
        (WorkflowRunStatus.CANCELLED, False),
    ],
)
async def test_inconsistent_state_is_rejected_without_nodes_or_release(
    setup, status, with_checkpoint
):
    setup.run.status = status
    checkpoint = (
        WorkflowCheckpoint(
            uuid4(), setup.run.id, 1, 1, ("start",), {"start": {}}, pending_node_id="value"
        )
        if with_checkpoint
        else None
    )
    setup.loader.return_value = (setup.definition, setup.run, checkpoint)
    with pytest.raises(BackgroundRunStateError):
        await setup.subject.execute(setup.job)
    setup.nodes.execute.assert_not_awaited()
    setup.claim_service.release.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [SQLAlchemyError("write failed"), RuntimeError("connection failed"), asyncio.CancelledError()],
)
async def test_persistence_errors_propagate_and_never_release_running(setup, error):
    setup.persistence.persist_node_completion.side_effect = error
    with pytest.raises(type(error)):
        await setup.subject.execute(setup.job)
    assert setup.nodes.execute.await_count == 1
    setup.persistence.persist_failure.assert_not_awaited()
    setup.claim_service.release.assert_not_awaited()


@pytest.mark.anyio
async def test_lost_lease_stops_nodes_and_does_not_release(setup):
    setup.persistence.persist_node_completion.side_effect = WorkflowExecutionLeaseLostError()
    result = await setup.subject.execute(setup.job)
    assert result.status is BackgroundRunExecutionStatus.LEASE_LOST
    assert setup.nodes.execute.await_count == 1
    setup.persistence.persist_failure.assert_not_awaited()
    setup.claim_service.release.assert_not_awaited()


@pytest.mark.anyio
async def test_node_failure_persists_failed_before_releasing(setup):
    setup.nodes.execute.side_effect = RuntimeError("node boom")
    result = await setup.subject.execute(setup.job)
    assert result.status is BackgroundRunExecutionStatus.FAILED and result.lease_released
    assert setup.run.error.code == "node_execution_failed"
    assert setup.run.finished_at is not None
    setup.persistence.persist_failure.assert_awaited_once_with(setup.run)
    setup.persistence.persist_node_completion.assert_not_awaited()


@pytest.mark.anyio
async def test_failure_persistence_error_retains_lease(setup):
    setup.nodes.execute.side_effect = RuntimeError("node boom")
    setup.persistence.persist_failure.side_effect = SQLAlchemyError("failure commit failed")
    with pytest.raises(SQLAlchemyError):
        await setup.subject.execute(setup.job)
    setup.claim_service.release.assert_not_awaited()


@pytest.mark.anyio
async def test_node_cancellation_propagates_without_failure_or_release(setup):
    setup.nodes.execute.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await setup.subject.execute(setup.job)
    assert setup.run.status is WorkflowRunStatus.RUNNING
    setup.persistence.persist_failure.assert_not_awaited()
    setup.claim_service.release.assert_not_awaited()


@pytest.mark.anyio
async def test_approval_pause_is_persisted_before_release_and_stops_downstream(setup):
    setup.definition.nodes[1].kind = WorkflowNodeKind.APPROVAL
    setup.definition.nodes[1].config = {"prompt": "Continue?"}

    async def dispatch(node, context):
        delegate = (
            ApprovalNodeExecutor()
            if node.kind is WorkflowNodeKind.APPROVAL
            else DeterministicNodeExecutor()
        )
        return await delegate.execute(node, context)

    setup.nodes.execute.side_effect = dispatch
    result = await setup.subject.execute(setup.job)
    assert result.status is BackgroundRunExecutionStatus.PAUSED and result.lease_released
    setup.persistence.persist_interruption.assert_awaited_once()
    assert setup.nodes.execute.await_count == 2
    setup.persistence.persist_failure.assert_not_awaited()


@pytest.mark.anyio
async def test_release_error_reports_committed_outcome_without_overwriting(setup):
    setup.claim_service.release.side_effect = SQLAlchemyError("release unavailable")
    result = await setup.subject.execute(setup.job)
    assert result.status is BackgroundRunExecutionStatus.COMPLETED
    assert not result.lease_released and "release unavailable" in result.release_error
    setup.persistence.persist_failure.assert_not_awaited()


@pytest.mark.anyio
async def test_engine_cannot_report_uncommitted_success(setup):
    async def no_persistence(definition, run, **kwargs):
        run.start()
        run.complete({})

    setup.engine.execute.side_effect = no_persistence
    with pytest.raises(BackgroundRunStateError, match="durably committed"):
        await setup.subject.execute(setup.job)
    setup.claim_service.release.assert_not_awaited()


@pytest.mark.anyio
async def test_duplicate_delivery_does_not_reexecute(setup):
    setup.claim_service.claim.side_effect = [setup.lease, None]
    assert (await setup.subject.execute(setup.job)).status is BackgroundRunExecutionStatus.COMPLETED
    assert (
        await setup.subject.execute(setup.job)
    ).status is BackgroundRunExecutionStatus.NOT_CLAIMED
    assert setup.nodes.execute.await_count == 3


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["claim", "load"])
async def test_infrastructure_read_and_claim_errors_propagate(setup, stage):
    target = setup.claim_service.claim if stage == "claim" else setup.loader
    target.side_effect = SQLAlchemyError("database unavailable")
    with pytest.raises(SQLAlchemyError):
        await setup.subject.execute(setup.job)
    setup.nodes.execute.assert_not_awaited()
    setup.claim_service.release.assert_not_awaited()


@pytest.mark.anyio
async def test_load_uses_persisted_snapshot_revision_and_short_read_session(setup, monkeypatch):
    row = SimpleNamespace(
        id=setup.run.id,
        workflow_id=setup.run.workflow_id,
        workflow_revision=1,
        status="pending",
        input={},
        node_outputs={},
        output=None,
        error=None,
        started_at=None,
        finished_at=None,
        definition_snapshot=serialize_workflow_graph(setup.definition),
        execution_claim_token=setup.lease.claim_token,
        execution_claim_generation=1,
        execution_lease_expires_at=setup.lease.expires_at,
    )
    db = MagicMock(spec=AsyncSession)
    db.__aenter__.return_value = db
    db.scalar.return_value = datetime(2026, 1, 1, tzinfo=UTC)
    factory = MagicMock(return_value=db)
    monkeypatch.setattr(module.run_repo, "get_workflow_run_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(
        module.checkpoint_repo, "get_latest_workflow_checkpoint", AsyncMock(return_value=None)
    )
    subject = BackgroundRunExecutor(factory, setup.engine, lease_duration=timedelta(minutes=1))
    definition, run, checkpoint = await subject._load(setup.lease)
    assert definition.revision == 1 and definition.nodes[1].config["value"] == "V1"
    assert run.workflow_revision == 1 and checkpoint is None
    db.__aexit__.assert_awaited_once()
    row.execution_claim_token = uuid4()
    with pytest.raises(WorkflowExecutionLeaseLostError):
        await subject._load(setup.lease)


def test_public_exports_and_result_immutability():
    from app.services.workflow import application
    from app.services.workflow.application import background

    for module_ in (workflow, application, background):
        for name in (
            "BackgroundRunExecutor",
            "BackgroundRunExecutionResult",
            "BackgroundRunExecutionStatus",
            "BackgroundRunStateError",
            "FencedDurableWorkflowExecutionPersistence",
            "WorkflowCheckpointSequenceError",
            "WorkflowExecutionLeaseLostError",
        ):
            assert getattr(module_, name) is getattr(workflow, name)
            assert name in module_.__all__
    result = BackgroundRunExecutionResult(uuid4(), BackgroundRunExecutionStatus.NOT_CLAIMED)
    with pytest.raises(FrozenInstanceError):
        result.status = BackgroundRunExecutionStatus.COMPLETED
