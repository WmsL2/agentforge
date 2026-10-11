"""Opt-in real PostgreSQL proofs for fenced background workflow execution."""

import asyncio
from datetime import timedelta
from itertools import pairwise
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.models.workflow import ApprovalRequest, Workflow, WorkflowRun
from app.db.models.workflow import WorkflowCheckpoint as DBCheckpoint
from app.db.models.workspace import Workspace
from app.repositories.workflow.run import claim as claim_repo
from app.services.workflow import (
    ApprovalNodeExecutor,
    BackgroundRunExecutionStatus,
    BackgroundRunExecutor,
    BackgroundRunStateError,
    DeterministicNodeExecutor,
    NodeExecutionResult,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowExecutionJob,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowResumeValidationError,
    serialize_workflow_graph,
)
from app.services.workflow.application.background import durability

pytestmark = pytest.mark.anyio
DURATION = timedelta(minutes=2)


class SimulatedProcessCrash(BaseException):
    """A test-only process interruption that must not become a node failure."""


class RecordingNodes:
    def __init__(self, hook=None):
        self.calls = []
        self.hook = hook

    async def execute(self, node, context):
        self.calls.append(node.id)
        if self.hook is not None:
            result = await self.hook(node, context)
            if result is not None:
                return result
        delegate = (
            ApprovalNodeExecutor()
            if node.kind is WorkflowNodeKind.APPROVAL
            else DeterministicNodeExecutor()
        )
        return await delegate.execute(node, context)


def definition(*, approval=False):
    nodes = [
        WorkflowNode("start", WorkflowNodeKind.START),
        WorkflowNode("a", WorkflowNodeKind.VALUE, config={"value": "A"}),
    ]
    if approval:
        nodes.append(
            WorkflowNode("approval", WorkflowNodeKind.APPROVAL, config={"prompt": "Continue?"})
        )
    nodes.extend(
        (
            WorkflowNode("b", WorkflowNodeKind.VALUE, config={"value": "B"}),
            WorkflowNode("end", WorkflowNodeKind.END),
        )
    )
    return WorkflowDefinition(
        uuid4(),
        "Background proof",
        "start",
        nodes=tuple(nodes),
        edges=tuple(
            WorkflowEdge(f"{source.id}-{target.id}", source.id, target.id)
            for source, target in pairwise(nodes)
        ),
    )


@pytest.fixture
async def make_run(postgres_restart_session_factory):
    if settings.POSTGRES_DB != "agentforge_v09_atomic3_verify":
        pytest.skip("Background proof requires POSTGRES_DB=agentforge_v09_atomic3_verify.")
    factory = postgres_restart_session_factory
    workspace_ids = []

    async def create(*, approval=False):
        graph = definition(approval=approval)
        workspace_id, run_id = uuid4(), uuid4()
        workspace_ids.append(workspace_id)
        snapshot = serialize_workflow_graph(graph)
        async with factory() as db:
            db.add(Workspace(id=workspace_id, name="Atomic 3 proof"))
            await db.flush()
            db.add(
                Workflow(
                    id=graph.id,
                    workspace_id=workspace_id,
                    name=graph.name,
                    definition=snapshot,
                    revision=1,
                )
            )
            await db.flush()
            db.add(
                WorkflowRun(
                    id=run_id,
                    workflow_id=graph.id,
                    workflow_revision=1,
                    definition_snapshot=snapshot,
                    status="pending",
                    input={"source": "original"},
                )
            )
            await db.commit()
        return graph, WorkflowExecutionJob(run_id)

    try:
        yield create
    finally:
        async with factory() as db:
            await db.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
            await db.commit()


def executor(factory, nodes, *, duration=DURATION):
    return BackgroundRunExecutor(factory, WorkflowEngine(nodes), lease_duration=duration)


async def stored(factory, run_id):
    async with factory() as db:
        run = await db.get(WorkflowRun, run_id)
        checkpoints = list(
            (
                await db.scalars(
                    select(DBCheckpoint)
                    .where(DBCheckpoint.run_id == run_id)
                    .order_by(DBCheckpoint.sequence)
                )
            ).all()
        )
        approvals = list(
            (
                await db.scalars(select(ApprovalRequest).where(ApprovalRequest.run_id == run_id))
            ).all()
        )
        assert run is not None
        return run, checkpoints, approvals


async def expire(factory, run_id):
    async with factory() as db:
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(execution_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
        await db.commit()


async def wait_for_expiry(factory, run_id):
    async with factory() as db:
        await db.execute(
            select(
                func.pg_sleep(
                    func.greatest(
                        0,
                        func.extract(
                            "epoch", WorkflowRun.execution_lease_expires_at - func.clock_timestamp()
                        ),
                    )
                    + 0.05
                )
            ).where(WorkflowRun.id == run_id)
        )


async def wait_for_blocked(factory, pid):
    async with asyncio.timeout(10), factory() as db:
        while not await db.scalar(select(func.cardinality(func.pg_blocking_pids(pid)) > 0)):
            await asyncio.sleep(0.01)


async def test_pending_run_completes_and_persists_all_outputs_and_checkpoints(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    _, job = await make_run()
    nodes = RecordingNodes()
    result = await executor(factory, nodes).execute(job)
    assert result.status is BackgroundRunExecutionStatus.COMPLETED and result.lease_released
    run, checkpoints, approvals = await stored(factory, job.run_id)
    assert run.status == "completed" and run.output == {"end": {"b": "B"}}
    assert run.node_outputs == {
        "start": {"source": "original"},
        "a": "A",
        "b": "B",
        "end": {"b": "B"},
    }
    assert run.started_at is not None and run.finished_at is not None
    assert nodes.calls == ["start", "a", "b", "end"]
    assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 2, 3, 4]
    assert [checkpoint.pending_node_id for checkpoint in checkpoints] == ["a", "b", "end", None]
    assert checkpoints[-1].node_outputs == run.node_outputs
    assert run.execution_claim_token is None and run.execution_lease_expires_at is None
    assert run.execution_claim_generation == 1 and approvals == []
    assert (
        await executor(factory, nodes).execute(job)
    ).status is BackgroundRunExecutionStatus.NOT_CLAIMED
    assert len(nodes.calls) == 4


async def test_two_background_attempts_execute_nodes_only_once(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    _, job = await make_run()
    entered, finish = asyncio.Event(), asyncio.Event()

    async def hold_first_node(node, context):
        if node.id == "start":
            entered.set()
            await finish.wait()

    first_nodes, second_nodes = RecordingNodes(hold_first_node), RecordingNodes()
    task = asyncio.create_task(executor(factory, first_nodes).execute(job))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        duplicate = await asyncio.wait_for(executor(factory, second_nodes).execute(job), 10)
        assert duplicate.status is BackgroundRunExecutionStatus.NOT_CLAIMED
        assert second_nodes.calls == []
        finish.set()
        assert (await asyncio.wait_for(task, 10)).status is BackgroundRunExecutionStatus.COMPLETED
    finally:
        finish.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    run, checkpoints, _ = await stored(factory, job.run_id)
    assert run.execution_claim_generation == 1 and len(checkpoints) == 4


@pytest.mark.parametrize("error", [SimulatedProcessCrash, asyncio.CancelledError])
async def test_crash_or_cancellation_retains_lease_and_recovers_after_committed_nodes(
    postgres_restart_session_factory, make_run, error
):
    factory = postgres_restart_session_factory
    _, job = await make_run()

    async def interrupt_b(node, context):
        if node.id == "b":
            raise error()

    old_nodes = RecordingNodes(interrupt_b)
    with pytest.raises(error):
        await executor(factory, old_nodes).execute(job)
    old, checkpoints, _ = await stored(factory, job.run_id)
    assert old.status == "running" and old.execution_claim_token is not None
    assert old.execution_lease_expires_at is not None
    assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 2]
    assert old.node_outputs == checkpoints[-1].node_outputs
    await expire(factory, job.run_id)
    claimed_tokens = []

    async def record_claim(node, context):
        row, _, _ = await stored(factory, job.run_id)
        claimed_tokens.append(row.execution_claim_token)

    new_nodes = RecordingNodes(record_claim)
    assert (
        await executor(factory, new_nodes).execute(job)
    ).status is BackgroundRunExecutionStatus.COMPLETED
    current, checkpoints, _ = await stored(factory, job.run_id)
    assert new_nodes.calls == ["b", "end"]
    assert current.execution_claim_generation == 2
    assert claimed_tokens[0] != old.execution_claim_token
    assert current.started_at == old.started_at
    assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 2, 3, 4]


async def test_new_worker_completion_cannot_be_overwritten_by_old_worker(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    _, job = await make_run()
    new_nodes = RecordingNodes()

    async def takeover(node, context):
        if node.id == "b":
            await expire(factory, job.run_id)
            assert (
                await executor(factory, new_nodes).execute(job)
            ).status is BackgroundRunExecutionStatus.COMPLETED
            return NodeExecutionResult(output="stale-old-output")

    old_nodes = RecordingNodes(takeover)
    result = await executor(factory, old_nodes).execute(job)
    assert result.status is BackgroundRunExecutionStatus.LEASE_LOST and not result.lease_released
    run, checkpoints, _ = await stored(factory, job.run_id)
    assert run.status == "completed" and run.node_outputs["b"] == "B"
    assert old_nodes.calls == ["start", "a", "b"] and new_nodes.calls == ["b", "end"]
    assert run.execution_claim_generation == 2 and len(checkpoints) == 4


async def test_expired_worker_cannot_append_checkpoint_or_continue(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    _, job = await make_run()

    async def lose_lease(node, context):
        if node.id == "b":
            await expire(factory, job.run_id)

    nodes = RecordingNodes(lose_lease)
    assert (
        await executor(factory, nodes).execute(job)
    ).status is BackgroundRunExecutionStatus.LEASE_LOST
    row, checkpoints, _ = await stored(factory, job.run_id)
    assert row.status == "running" and "b" not in row.node_outputs
    assert row.execution_claim_token is not None and row.execution_lease_expires_at is not None
    assert len(checkpoints) == 2 and nodes.calls == ["start", "a", "b"]


@pytest.mark.parametrize("failed_sequence,pending_node", [(3, "b"), (4, "end")])
async def test_sql_failure_after_run_update_rolls_back_and_leaves_recoverable_lease(
    postgres_restart_session_factory, make_run, monkeypatch, failed_sequence, pending_node
):
    factory = postgres_restart_session_factory
    _, job = await make_run()
    original = durability.checkpoint_repo.create_workflow_checkpoint

    async def fail_before_checkpoint(db, *, checkpoint):
        if checkpoint.sequence == failed_sequence:
            await db.execute(text("SELECT 1 / 0"))
        return await original(db, checkpoint=checkpoint)

    with monkeypatch.context() as patch:
        patch.setattr(
            durability.checkpoint_repo, "create_workflow_checkpoint", fail_before_checkpoint
        )
        with pytest.raises(SQLAlchemyError):
            await executor(factory, RecordingNodes()).execute(job)
    row, checkpoints, _ = await stored(factory, job.run_id)
    assert row.status == "running" and pending_node not in row.node_outputs
    assert len(checkpoints) == failed_sequence - 1
    assert row.node_outputs == checkpoints[-1].node_outputs
    assert row.output is None and row.finished_at is None
    assert row.execution_claim_token is not None and row.execution_lease_expires_at is not None
    await expire(factory, job.run_id)
    nodes = RecordingNodes()
    assert (
        await executor(factory, nodes).execute(job)
    ).status is BackgroundRunExecutionStatus.COMPLETED
    assert nodes.calls == (["b", "end"] if pending_node == "b" else ["end"])
    row, checkpoints, _ = await stored(factory, job.run_id)
    assert row.execution_claim_generation == 2 and len(checkpoints) == 4


async def test_crash_before_first_checkpoint_leaves_pending_and_can_restart(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    _, job = await make_run()

    async def crash(node, context):
        raise SimulatedProcessCrash()

    with pytest.raises(SimulatedProcessCrash):
        await executor(factory, RecordingNodes(crash)).execute(job)
    row, checkpoints, _ = await stored(factory, job.run_id)
    assert row.status == "pending" and row.started_at is None
    assert row.execution_claim_token is not None and row.execution_lease_expires_at is not None
    assert checkpoints == [] and row.node_outputs == {}
    await expire(factory, job.run_id)
    nodes = RecordingNodes()
    assert (
        await executor(factory, nodes).execute(job)
    ).status is BackgroundRunExecutionStatus.COMPLETED
    row, checkpoints, _ = await stored(factory, job.run_id)
    assert nodes.calls == ["start", "a", "b", "end"]
    assert row.execution_claim_generation == 2
    assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 2, 3, 4]


@pytest.mark.parametrize("failing_node,count", [("start", 0), ("b", 2)])
async def test_node_failure_is_durable_and_has_no_success_checkpoint(
    postgres_restart_session_factory, make_run, failing_node, count
):
    factory = postgres_restart_session_factory
    _, job = await make_run()

    async def fail(node, context):
        if node.id == failing_node:
            raise RuntimeError("node boom")

    result = await executor(factory, RecordingNodes(fail)).execute(job)
    assert result.status is BackgroundRunExecutionStatus.FAILED and result.lease_released
    row, checkpoints, _ = await stored(factory, job.run_id)
    assert row.status == "failed" and row.finished_at is not None
    assert row.error == {
        "code": "node_execution_failed",
        "message": "node boom",
        "node_id": failing_node,
    }
    assert len(checkpoints) == count and failing_node not in row.node_outputs
    assert row.execution_claim_token is None


async def test_approval_atomically_pauses_and_creates_request_without_downstream_execution(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    _, job = await make_run(approval=True)
    nodes = RecordingNodes()
    result = await executor(factory, nodes).execute(job)
    assert result.status is BackgroundRunExecutionStatus.PAUSED and result.lease_released
    row, checkpoints, approvals = await stored(factory, job.run_id)
    assert row.status == "paused" and row.finished_at is None
    assert nodes.calls == ["start", "a", "approval"]
    assert len(approvals) == 1 and approvals[0].status == "pending"
    assert approvals[0].node_id == "approval"
    assert checkpoints[-1].sequence == 3 and checkpoints[-1].pending_node_id == "approval"
    assert checkpoints[-1].completed_node_ids == ["start", "a"]
    assert checkpoints[-1].interrupt["type"] == "approval_required"
    assert row.execution_claim_token is None and row.execution_lease_expires_at is None


async def test_approval_insert_failure_rolls_back_pause_and_checkpoint(
    postgres_restart_session_factory, make_run, monkeypatch
):
    factory = postgres_restart_session_factory
    _, job = await make_run(approval=True)

    async def fail_approval(db, **kwargs):
        await db.execute(text("SELECT 1 / 0"))

    with monkeypatch.context() as patch:
        patch.setattr(durability.approval_repo, "create_approval_request", fail_approval)
        with pytest.raises(SQLAlchemyError):
            await executor(factory, RecordingNodes()).execute(job)
    row, checkpoints, approvals = await stored(factory, job.run_id)
    assert row.status == "running" and len(checkpoints) == 2 and approvals == []
    assert row.execution_claim_token is not None


async def test_current_workflow_v2_does_not_replace_run_snapshot_v1(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    graph, job = await make_run()
    graph.nodes[1].config["value"] = "A-V2"
    graph.nodes[2].config["value"] = "B-V2"
    async with factory() as db:
        await db.execute(
            update(Workflow)
            .where(Workflow.id == graph.id)
            .values(definition=serialize_workflow_graph(graph), revision=2)
        )
        await db.commit()
    assert (
        await executor(factory, RecordingNodes()).execute(job)
    ).status is BackgroundRunExecutionStatus.COMPLETED
    row, checkpoints, _ = await stored(factory, job.run_id)
    assert (
        row.workflow_revision == 1 and row.node_outputs["a"] == "A" and row.node_outputs["b"] == "B"
    )
    assert row.output == {"end": {"b": "B"}}
    assert all(checkpoint.workflow_revision == 1 for checkpoint in checkpoints)


@pytest.mark.parametrize(
    "case", ["pending_checkpoint", "running_no_checkpoint", "running_all_complete"]
)
async def test_invalid_persisted_states_refuse_execution_without_clearing_lease(
    postgres_restart_session_factory, make_run, case
):
    factory = postgres_restart_session_factory
    graph, job = await make_run()
    async with factory() as db:
        if case.startswith("running"):
            await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == job.run_id)
                .values(
                    status="running",
                    execution_claim_token=uuid4(),
                    execution_claim_generation=1,
                    execution_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1),
                )
            )
        if case != "running_no_checkpoint":
            complete = case == "running_all_complete"
            outputs = {node.id: {} for node in graph.nodes} if complete else {"start": {}}
            db.add(
                DBCheckpoint(
                    id=uuid4(),
                    run_id=job.run_id,
                    workflow_revision=1,
                    sequence=1,
                    completed_node_ids=list(outputs),
                    node_outputs=outputs,
                    pending_node_id=None if complete else "a",
                )
            )
        await db.commit()
    nodes = RecordingNodes()
    expected = (
        WorkflowResumeValidationError if case == "running_all_complete" else BackgroundRunStateError
    )
    with pytest.raises(expected):
        await executor(factory, nodes).execute(job)
    row, checkpoints, _ = await stored(factory, job.run_id)
    assert nodes.calls == [] and row.execution_claim_token is not None
    assert row.status == ("pending" if case == "pending_checkpoint" else "running")
    assert len(checkpoints) == (0 if case == "running_no_checkpoint" else 1)


async def test_corrupt_snapshot_propagates_without_failure_write_or_release(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    _, job = await make_run()
    async with factory() as db:
        await db.execute(
            update(WorkflowRun).where(WorkflowRun.id == job.run_id).values(definition_snapshot={})
        )
        await db.commit()
    nodes = RecordingNodes()
    with pytest.raises(ValueError, match="missing required keys"):
        await executor(factory, nodes).execute(job)
    row, checkpoints, _ = await stored(factory, job.run_id)
    assert row.status == "pending" and row.execution_claim_token is not None
    assert row.error is None and checkpoints == [] and nodes.calls == []


async def test_node_execution_holds_no_workflow_run_row_lock(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    _, job = await make_run()

    async def independently_lock(node, context):
        async with factory() as db, db.begin():
            assert (
                await db.scalar(
                    select(WorkflowRun.id)
                    .where(WorkflowRun.id == job.run_id)
                    .with_for_update(nowait=True)
                )
                == job.run_id
            )

    assert (
        await executor(factory, RecordingNodes(independently_lock)).execute(job)
    ).status is BackgroundRunExecutionStatus.COMPLETED


async def test_fencing_lock_is_held_through_checkpoint_transaction_and_rollback(
    postgres_restart_session_factory, make_run, monkeypatch
):
    factory = postgres_restart_session_factory
    _, job = await make_run()
    checkpoint_entered, abort_old, claim_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    old_pids, new_pids = [], []
    original_insert = durability.checkpoint_repo.create_workflow_checkpoint
    original_claim = claim_repo.claim_execution

    async def hold_checkpoint_transaction(db, *, checkpoint):
        if checkpoint.sequence == 3 and not checkpoint_entered.is_set():
            old_pids.append(await db.scalar(select(func.pg_backend_pid())))
            checkpoint_entered.set()
            await abort_old.wait()
            await db.execute(text("SELECT 1 / 0"))
        return await original_insert(db, checkpoint=checkpoint)

    async def record_new_claim(db, *args):
        new_pids.append(await db.scalar(select(func.pg_backend_pid())))
        claim_started.set()
        return await original_claim(db, *args)

    old_task = new_task = None
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                durability.checkpoint_repo,
                "create_workflow_checkpoint",
                hold_checkpoint_transaction,
            )
            old_task = asyncio.create_task(
                executor(factory, RecordingNodes(), duration=timedelta(seconds=5)).execute(job)
            )
            await asyncio.wait_for(checkpoint_entered.wait(), 10)
            await wait_for_expiry(factory, job.run_id)
            patch.setattr(claim_repo, "claim_execution", record_new_claim)
            new_nodes = RecordingNodes()
            new_task = asyncio.create_task(executor(factory, new_nodes).execute(job))
            await asyncio.wait_for(claim_started.wait(), 10)
            assert new_pids[0] != old_pids[0]
            await wait_for_blocked(factory, new_pids[0])
            assert not new_task.done()
            abort_old.set()
            with pytest.raises(SQLAlchemyError):
                await asyncio.wait_for(old_task, 10)
            assert (
                await asyncio.wait_for(new_task, 10)
            ).status is BackgroundRunExecutionStatus.COMPLETED
        row, checkpoints, _ = await stored(factory, job.run_id)
        assert row.status == "completed" and row.execution_claim_generation == 2
        assert new_nodes.calls == ["b", "end"]
        assert [checkpoint.sequence for checkpoint in checkpoints] == [1, 2, 3, 4]
    finally:
        abort_old.set()
        for task in (old_task, new_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (old_task, new_task) if task is not None), return_exceptions=True
        )
