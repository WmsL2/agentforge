"""Metadata tests for workflow observability ORM models."""

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.db.models.workflow import WorkflowRunStep, WorkflowTraceEvent


def test_workflow_run_step_table_has_the_expected_persistence_contract() -> None:
    table = WorkflowRunStep.__table__

    assert table.name == "workflow_run_steps"
    assert {
        "id",
        "run_id",
        "sequence",
        "node_id",
        "node_kind",
        "status",
        "input",
        "output",
        "error",
        "metadata",
        "started_at",
        "finished_at",
    } == set(table.columns.keys())
    assert table.c.output.nullable is True
    assert table.c.error.nullable is True
    assert table.c.finished_at.nullable is True
    assert all(
        column.nullable is False
        for column in table.c
        if column.name not in {"output", "error", "finished_at"}
    )
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


def test_workflow_trace_event_table_has_the_expected_persistence_contract() -> None:
    table = WorkflowTraceEvent.__table__

    assert table.name == "workflow_trace_events"
    assert {"id", "run_id", "step_id", "kind", "payload", "created_at"} == set(table.columns.keys())
    assert table.c.step_id.nullable is True
    assert all(table.c[name].nullable is False for name in {"id", "run_id", "kind", "payload", "created_at"})
    assert next(iter(table.c.run_id.foreign_keys)).target_fullname == "workflow_runs.id"
    assert next(iter(table.c.step_id.foreign_keys)).target_fullname == "workflow_run_steps.id"
    assert {tuple(index.columns.keys()) for index in table.indexes} == {
        ("run_id", "created_at"),
        ("step_id",),
    }
