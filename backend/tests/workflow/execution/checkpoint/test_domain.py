"""Tests for immutable workflow checkpoint domain snapshots."""

from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

import pytest

from app.services.workflow import WorkflowCheckpoint

CREATED_AT = datetime(2026, 9, 14, 10, tzinfo=UTC)


def make_checkpoint(**kwargs: object) -> WorkflowCheckpoint:
    values: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "workflow_revision": 3,
        "sequence": 1,
        "completed_node_ids": ("start",),
        "node_outputs": {"start": {"request": "hello"}},
        "created_at": CREATED_AT,
    }
    values.update(kwargs)
    return WorkflowCheckpoint(**values)  # type: ignore[arg-type]


def test_checkpoint_constructs_immutable_top_level_snapshots() -> None:
    checkpoint = make_checkpoint(pending_node_id="value", interrupt={"kind": "approval"})

    assert checkpoint.completed_node_ids == ("start",)
    assert isinstance(checkpoint.node_outputs, MappingProxyType)
    assert isinstance(checkpoint.interrupt, MappingProxyType)
    assert checkpoint.pending_node_id == "value"
    assert checkpoint.created_at == CREATED_AT


def test_completed_node_ids_are_copied_to_a_tuple_snapshot() -> None:
    completed_node_ids = ["start", "value"]

    checkpoint = make_checkpoint(completed_node_ids=completed_node_ids)
    completed_node_ids.append("end")

    assert checkpoint.completed_node_ids == ("start", "value")


def test_node_outputs_are_independent_read_only_top_level_snapshot() -> None:
    node_outputs = {"start": {"request": "hello"}}
    checkpoint = make_checkpoint(node_outputs=node_outputs)
    node_outputs["value"] = 42

    assert checkpoint.node_outputs == {"start": {"request": "hello"}}
    with pytest.raises(TypeError):
        checkpoint.node_outputs["injected"] = "no"  # type: ignore[index]


def test_interrupt_is_independent_read_only_top_level_snapshot() -> None:
    interrupt = {"kind": "approval"}
    checkpoint = make_checkpoint(interrupt=interrupt)
    interrupt["reason"] = "later"

    assert checkpoint.interrupt == {"kind": "approval"}
    assert checkpoint.interrupt is not None
    with pytest.raises(TypeError):
        checkpoint.interrupt["injected"] = "no"  # type: ignore[index]


def test_sequence_one_is_valid() -> None:
    assert make_checkpoint(sequence=1).sequence == 1


@pytest.mark.parametrize("sequence", [0, -1])
def test_non_positive_sequence_is_rejected(sequence: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        make_checkpoint(sequence=sequence)


def test_duplicate_completed_node_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        make_checkpoint(completed_node_ids=("start", "start"))


def test_pending_node_cannot_already_be_completed() -> None:
    with pytest.raises(ValueError, match="cannot already be completed"):
        make_checkpoint(pending_node_id="start")
