"""AsyncMock tests for workflow observability persistence primitives."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories.workflow.observability import run_step, trace_event
from app.services.workflow import (
    RunStep,
    RunStepError,
    TraceEvent,
    TraceEventKind,
    WorkflowNodeKind,
)

STARTED_AT = datetime(2026, 9, 16, 9, 30, tzinfo=UTC)
FINISHED_AT = datetime(2026, 9, 16, 9, 45, tzinfo=UTC)


def make_step(**kwargs: object) -> RunStep:
    values: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "sequence": 2,
        "node_id": "value",
        "node_kind": WorkflowNodeKind.VALUE,
        "input": {"request": "hello"},
        "metadata": {"attempt": 2},
        "started_at": STARTED_AT,
    }
    values.update(kwargs)
    return RunStep(**values)  # type: ignore[arg-type]


def make_event(**kwargs: object) -> TraceEvent:
    values: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "step_id": uuid4(),
        "kind": TraceEventKind.NODE_STARTED,
        "payload": {"node_id": "value"},
        "created_at": STARTED_AT,
    }
    values.update(kwargs)
    return TraceEvent(**values)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_create_run_step_uses_serialized_state_without_committing() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    step = make_step()

    created = await run_step.create_workflow_run_step(db, step=step)

    assert (created.id, created.run_id, created.sequence) == (step.id, step.run_id, 2)
    assert (created.node_id, created.node_kind, created.status) == ("value", "value", "running")
    assert created.input == {"request": "hello"}
    assert created.metadata_ == {"attempt": 2}
    assert created.started_at == STARTED_AT
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_update_run_step_changes_only_mutable_execution_state() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    immutable = SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        sequence=9,
        node_id="fixed",
        node_kind="agent",
        input={"fixed": True},
        started_at=STARTED_AT,
        status="running",
        output=None,
        error=None,
        metadata_={"stale": True},
        finished_at=None,
    )
    step = make_step(id=immutable.id, run_id=uuid4(), sequence=1, node_id="different")
    step.fail(RunStepError(code="failed", message="boom"), {"duration_ms": 10}, at=FINISHED_AT)

    updated = await run_step.update_workflow_run_step_state(db, db_step=immutable, step=step)

    assert updated is immutable
    assert (immutable.id, immutable.sequence, immutable.node_id, immutable.node_kind) == (
        immutable.id,
        9,
        "fixed",
        "agent",
    )
    assert immutable.run_id != step.run_id
    assert immutable.input == {"fixed": True}
    assert immutable.started_at == STARTED_AT
    assert immutable.status == "failed"
    assert immutable.output is None
    assert immutable.error == {"code": "failed", "message": "boom"}
    assert immutable.metadata_ == {"duration_ms": 10}
    assert immutable.finished_at == FINISHED_AT
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_get_and_list_run_steps_use_identity_and_sequence_order() -> None:
    db = AsyncMock()
    stored = SimpleNamespace(id=uuid4())
    result = MagicMock()
    result.scalars.return_value.all.return_value = [stored]
    db.get.return_value = stored
    db.execute.return_value = result

    assert await run_step.get_workflow_run_step_by_id(db, stored.id) is stored
    assert await run_step.list_workflow_run_steps(db, uuid4()) == [stored]
    statement = db.execute.await_args.args[0]
    assert "workflow_run_steps.run_id" in str(statement)
    assert "ORDER BY workflow_run_steps.sequence ASC" in str(statement)


@pytest.mark.anyio
async def test_create_trace_event_is_append_only_and_does_not_commit() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    event = make_event()

    created = await trace_event.create_workflow_trace_event(db, event=event)

    assert (created.id, created.run_id, created.step_id) == (event.id, event.run_id, event.step_id)
    assert created.kind == "node_started"
    assert created.payload == {"node_id": "value"}
    assert created.created_at == STARTED_AT
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)
    db.commit.assert_not_awaited()
    assert not hasattr(trace_event, "update_workflow_trace_event")
    assert not hasattr(trace_event, "delete_workflow_trace_event")


@pytest.mark.anyio
async def test_list_trace_events_uses_stable_created_at_then_id_order() -> None:
    db = AsyncMock()
    stored = SimpleNamespace(id=uuid4())
    result = MagicMock()
    result.scalars.return_value.all.return_value = [stored]
    db.execute.return_value = result

    assert await trace_event.list_workflow_trace_events(db, uuid4()) == [stored]

    statement = db.execute.await_args.args[0]
    assert "workflow_trace_events.run_id" in str(statement)
    assert "ORDER BY workflow_trace_events.created_at ASC, workflow_trace_events.id ASC" in str(statement)
