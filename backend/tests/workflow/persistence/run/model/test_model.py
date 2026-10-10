"""Metadata tests for the workflow-run ORM model."""

from sqlalchemy import CheckConstraint, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID

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


def test_workflow_run_execution_claim_metadata_and_constraints() -> None:
    table = WorkflowRun.__table__
    token = table.c.execution_claim_token
    expires = table.c.execution_lease_expires_at
    generation = table.c.execution_claim_generation
    assert isinstance(token.type, UUID) and token.type.as_uuid
    assert token.nullable and token.default is None and token.server_default is None
    assert isinstance(expires.type, DateTime) and expires.type.timezone
    assert expires.nullable and expires.default is None and expires.server_default is None
    assert isinstance(generation.type, Integer) and not generation.nullable
    assert generation.default.arg == 0
    assert str(generation.server_default.arg) == "0"
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert constraints == {
        "workflow_runs_execution_claim_generation_nonnegative_check": "execution_claim_generation >= 0",
        "workflow_runs_execution_claim_lease_pair_check": "(execution_claim_token IS NULL) = (execution_lease_expires_at IS NULL)",
    }
