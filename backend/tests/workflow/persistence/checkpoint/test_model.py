"""Metadata tests for the workflow checkpoint ORM model."""

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.db.models.workflow import WorkflowCheckpoint


def test_workflow_checkpoint_table_has_the_expected_persistence_contract() -> None:
    table = WorkflowCheckpoint.__table__

    assert table.name == "workflow_checkpoints"
    assert {
        "id",
        "run_id",
        "workflow_revision",
        "sequence",
        "completed_node_ids",
        "node_outputs",
        "pending_node_id",
        "interrupt",
        "created_at",
    } == set(table.columns.keys())
    assert table.c.run_id.nullable is False
    assert table.c.workflow_revision.nullable is False
    assert table.c.sequence.nullable is False
    assert table.c.completed_node_ids.nullable is False
    assert table.c.node_outputs.nullable is False
    assert table.c.pending_node_id.nullable is True
    assert table.c.interrupt.nullable is True
    assert table.c.created_at.nullable is False
    assert next(iter(table.c.run_id.foreign_keys)).target_fullname == "workflow_runs.id"
    assert any(
        isinstance(constraint, UniqueConstraint)
        and set(constraint.columns.keys()) == {"run_id", "sequence"}
        for constraint in table.constraints
    )
    assert any(
        isinstance(constraint, CheckConstraint) and constraint.sqltext.text == "sequence >= 1"
        for constraint in table.constraints
    )
