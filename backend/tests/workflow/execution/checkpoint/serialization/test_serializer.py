"""Tests for pure workflow checkpoint persistence-state serialization."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.services.workflow.execution.checkpoint import (
    WorkflowCheckpoint,
    deserialize_workflow_checkpoint,
    serialize_workflow_checkpoint_state,
)

CREATED_AT = datetime(2026, 9, 14, 10, tzinfo=UTC)


def make_checkpoint(**kwargs: object) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        id=uuid4(),
        run_id=uuid4(),
        workflow_revision=4,
        sequence=2,
        completed_node_ids=("start", "value"),
        node_outputs={"start": {"request": "hello"}, "value": 42},
        pending_node_id="end",
        created_at=CREATED_AT,
        **kwargs,
    )  # type: ignore[arg-type]


def test_serialize_produces_jsonb_compatible_plain_structures() -> None:
    checkpoint = make_checkpoint(interrupt={"kind": "approval"})

    state = serialize_workflow_checkpoint_state(checkpoint)

    assert state == {
        "completed_node_ids": ["start", "value"],
        "node_outputs": {"start": {"request": "hello"}, "value": 42},
        "pending_node_id": "end",
        "interrupt": {"kind": "approval"},
        "created_at": CREATED_AT,
    }
    assert isinstance(state["node_outputs"], dict)
    assert isinstance(state["interrupt"], dict)


def test_deserialize_reconstructs_checkpoint_and_preserves_none_interrupt() -> None:
    checkpoint_id = uuid4()
    run_id = uuid4()
    completed_node_ids = ["start"]
    node_outputs = {"start": {"request": "hello"}}

    checkpoint = deserialize_workflow_checkpoint(
        checkpoint_id=checkpoint_id,
        run_id=run_id,
        workflow_revision=5,
        sequence=1,
        completed_node_ids=completed_node_ids,
        node_outputs=node_outputs,
        pending_node_id=None,
        interrupt=None,
        created_at=CREATED_AT,
    )
    completed_node_ids.append("value")
    node_outputs["value"] = 42

    assert checkpoint.id == checkpoint_id
    assert checkpoint.run_id == run_id
    assert checkpoint.completed_node_ids == ("start",)
    assert checkpoint.node_outputs == {"start": {"request": "hello"}}
    assert checkpoint.pending_node_id is None
    assert checkpoint.interrupt is None
    assert checkpoint.created_at == CREATED_AT


def test_deserialize_preserves_interrupt_mapping() -> None:
    checkpoint = deserialize_workflow_checkpoint(
        checkpoint_id=uuid4(),
        run_id=uuid4(),
        workflow_revision=5,
        sequence=1,
        completed_node_ids=[],
        node_outputs={},
        pending_node_id="start",
        interrupt={"kind": "approval"},
        created_at=CREATED_AT,
    )

    assert checkpoint.interrupt == {"kind": "approval"}
    assert checkpoint.pending_node_id == "start"


def test_deserialize_reapplies_domain_invariants() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        deserialize_workflow_checkpoint(
            checkpoint_id=uuid4(),
            run_id=uuid4(),
            workflow_revision=1,
            sequence=1,
            completed_node_ids=["start", "start"],
            node_outputs={},
            pending_node_id=None,
            interrupt=None,
            created_at=None,
        )
