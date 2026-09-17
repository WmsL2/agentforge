"""Unit tests for independent-transaction SQLAlchemy workflow observation."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.workflow import (
    NodeExecutionContext,
    NodeExecutionInterrupt,
    NodeExecutionOutcome,
    NodeExecutionResult,
    RunStepError,
    TraceEventKind,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowObservationContext,
)
from app.services.workflow.application.observability.observer import (
    SQLAlchemyWorkflowExecutionObserver,
)

STARTED_AT = datetime(2026, 9, 17, 9, tzinfo=UTC)


class SessionContext:
    def __init__(self, session: AsyncMock):
        self._session = session

    async def __aenter__(self) -> AsyncMock:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


def session_factory(*sessions: AsyncMock) -> MagicMock:
    contexts = iter(SessionContext(session) for session in sessions)
    return MagicMock(side_effect=lambda: next(contexts))


def session() -> AsyncMock:
    value = AsyncMock()
    value.add = MagicMock()
    return value


def running_step_row(*, run_id: object, step_id: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=step_id,
        run_id=run_id,
        sequence=2,
        node_id="value",
        node_kind="value",
        status="running",
        input={"workflow_input": {}, "upstream_outputs": {}, "node_outputs": {}},
        output=None,
        error=None,
        metadata_={},
        started_at=STARTED_AT,
        finished_at=None,
    )


def test_start_step_locks_parent_allocates_sequence_and_commits_step_with_event() -> None:
    db = session()
    run_id = uuid4()
    lock_result = MagicMock()
    lock_result.scalar_one_or_none.return_value = run_id
    db.execute.return_value = lock_result
    db.scalar.return_value = None
    observer = SQLAlchemyWorkflowExecutionObserver(session_factory(db))
    context = NodeExecutionContext(
        run_id=run_id,
        workflow_input={"request": "hello"},
        upstream_outputs={"start": {"request": "hello"}},
        node_outputs={"start": {"request": "hello"}},
    )

    observation = asyncio.run(
        observer.start_step(
            run_id=run_id,
            node=WorkflowNode("value", WorkflowNodeKind.VALUE, {"value": 3}),
            execution_context=context,
        )
    )

    added = [call.args[0] for call in db.add.call_args_list]
    step, event = added
    assert observation.run_id == run_id
    assert observation.step_id == step.id
    assert (step.run_id, step.sequence, step.node_id, step.node_kind, step.status) == (
        run_id,
        1,
        "value",
        "value",
        "running",
    )
    assert step.input == {
        "workflow_input": {"request": "hello"},
        "upstream_outputs": {"start": {"request": "hello"}},
        "node_outputs": {"start": {"request": "hello"}},
    }
    assert (event.step_id, event.kind, event.payload) == (
        step.id,
        "node_started",
        {"node_id": "value", "node_kind": "value"},
    )
    assert "FOR UPDATE" in str(db.execute.await_args.args[0].compile())
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


def test_start_step_allocates_after_existing_max_sequence() -> None:
    db = session()
    run_id = uuid4()
    result = MagicMock()
    result.scalar_one_or_none.return_value = run_id
    db.execute.return_value = result
    db.scalar.return_value = 7
    observer = SQLAlchemyWorkflowExecutionObserver(session_factory(db))

    asyncio.run(
        observer.start_step(
            run_id=run_id,
            node=WorkflowNode("value", WorkflowNodeKind.VALUE),
            execution_context=NodeExecutionContext(run_id=run_id, workflow_input={}, upstream_outputs={}, node_outputs={}),
        )
    )

    assert db.add.call_args_list[0].args[0].sequence == 8


def test_complete_reconstructs_domain_step_updates_and_commits_completed_event() -> None:
    db = session()
    run_id, step_id = uuid4(), uuid4()
    db.get.return_value = running_step_row(run_id=run_id, step_id=step_id)
    observer = SQLAlchemyWorkflowExecutionObserver(session_factory(db))
    result = NodeExecutionResult(output={"answer": "done"}, metadata={"duration_ms": 10})

    asyncio.run(observer.complete_step(WorkflowObservationContext(run_id, step_id), result=result))

    row = db.get.return_value
    event = db.add.call_args_list[-1].args[0]
    assert (row.status, row.output, row.error, row.metadata_) == (
        "completed",
        {"answer": "done"},
        None,
        {"duration_ms": 10},
    )
    assert event.kind == "node_completed"
    assert event.payload == {"node_id": "value", "node_kind": "value", "metadata": {"duration_ms": 10}}
    db.commit.assert_awaited_once()


def test_none_step_context_is_a_noop_for_lifecycle_callbacks() -> None:
    db = session()
    observer = SQLAlchemyWorkflowExecutionObserver(session_factory(db))
    context = WorkflowObservationContext(run_id=uuid4())

    asyncio.run(observer.complete_step(context, result=NodeExecutionResult()))
    asyncio.run(observer.fail_step(context, error=RunStepError("failed", "boom"), metadata={}))
    asyncio.run(
        observer.interrupt_step(
            context,
            result=NodeExecutionResult(
                outcome=NodeExecutionOutcome.INTERRUPTED,
                interrupt=NodeExecutionInterrupt(type="approval_required", payload={}),
            ),
        )
    )

    db.get.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("operation", "expected_status", "expected_kind"),
    [
        ("fail", "failed", "node_failed"),
        ("interrupt", "interrupted", "node_interrupted"),
    ],
)
def test_fail_and_interrupt_update_domain_step_and_append_events(
    operation: str, expected_status: str, expected_kind: str
) -> None:
    db = session()
    run_id, step_id = uuid4(), uuid4()
    db.get.return_value = running_step_row(run_id=run_id, step_id=step_id)
    observer = SQLAlchemyWorkflowExecutionObserver(session_factory(db))
    context = WorkflowObservationContext(run_id, step_id)

    if operation == "fail":
        asyncio.run(
            observer.fail_step(
                context,
                error=RunStepError("node_execution_failed", "boom"),
                metadata={"duration_ms": 10},
            )
        )
    else:
        asyncio.run(
            observer.interrupt_step(
                context,
                result=NodeExecutionResult(
                    metadata={"duration_ms": 10},
                    outcome=NodeExecutionOutcome.INTERRUPTED,
                    interrupt=NodeExecutionInterrupt(type="approval_required", payload={"prompt": "Continue?"}),
                ),
            )
        )

    row = db.get.return_value
    event = db.add.call_args_list[-1].args[0]
    assert row.status == expected_status
    assert event.kind == expected_kind
    assert event.payload["node_id"] == "value"
    assert event.payload["metadata"] == {"duration_ms": 10}
    db.commit.assert_awaited_once()


def test_record_event_persists_any_kind_with_a_none_step_id() -> None:
    db = session()
    run_id = uuid4()
    observer = SQLAlchemyWorkflowExecutionObserver(session_factory(db))

    asyncio.run(
        observer.record_event(
            WorkflowObservationContext(run_id),
            kind=TraceEventKind.APPROVAL_APPROVED,
            payload={"approval_id": "approval-1"},
        )
    )

    event = db.add.call_args.args[0]
    assert (event.run_id, event.step_id, event.kind, event.payload) == (
        run_id,
        None,
        "approval_approved",
        {"approval_id": "approval-1"},
    )
    db.commit.assert_awaited_once()


def test_persistence_failure_rolls_back_and_reraises_original_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    db = session()
    run_id = uuid4()
    result = MagicMock()
    result.scalar_one_or_none.return_value = run_id
    db.execute.return_value = result
    db.scalar.return_value = None
    observer = SQLAlchemyWorkflowExecutionObserver(session_factory(db))

    async def fail_create(*args: object, **kwargs: object) -> None:
        raise RuntimeError("flush failed")

    monkeypatch.setattr(
        "app.services.workflow.application.observability.observer.create_workflow_run_step",
        fail_create,
    )

    with pytest.raises(RuntimeError, match="flush failed"):
        asyncio.run(
            observer.start_step(
                run_id=run_id,
                node=WorkflowNode("value", WorkflowNodeKind.VALUE),
                execution_context=NodeExecutionContext(
                    run_id=run_id, workflow_input={}, upstream_outputs={}, node_outputs={}
                ),
            )
        )

    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
