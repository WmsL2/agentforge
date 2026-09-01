"""Metadata tests for the workflow-run ORM model."""

from app.db.models.workflow import WorkflowRun


def test_workflow_run_table_has_the_expected_persistence_contract() -> None:
    table = WorkflowRun.__table__

    assert table.name == "workflow_runs"
    assert {
        "id",
        "workflow_id",
        "workflow_revision",
        "definition_snapshot",
        "status",
        "input",
        "node_outputs",
        "output",
        "error",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    } <= set(table.columns.keys())
    assert table.c.workflow_id.nullable is False
    assert table.c.workflow_revision.nullable is False
    assert table.c.definition_snapshot.nullable is False
    assert table.c.status.nullable is False
    assert table.c.input.nullable is False
    assert table.c.node_outputs.nullable is False
    assert table.c.output.nullable is True
    assert table.c.error.nullable is True
    assert table.c.started_at.nullable is True
    assert table.c.finished_at.nullable is True
    assert next(iter(table.c.workflow_id.foreign_keys)).target_fullname == "workflows.id"
    assert any(index.columns.keys() == ["workflow_id"] for index in table.indexes)
