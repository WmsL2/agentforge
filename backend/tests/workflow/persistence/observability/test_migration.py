"""Static tests for the workflow observability Alembic migration."""

import runpy
from pathlib import Path
from unittest.mock import patch

MIGRATION = (
    Path(__file__).parents[4] / "alembic" / "versions" / "0037_create_workflow_observability.py"
)


def test_observability_migration_has_the_required_revision_chain() -> None:
    namespace = runpy.run_path(str(MIGRATION))

    assert namespace["revision"] == "0037_create_workflow_observability"
    assert namespace["down_revision"] == "0036_create_workflow_approval_requests"


def test_observability_migration_creates_and_drops_tables_in_dependency_order() -> None:
    namespace = runpy.run_path(str(MIGRATION))
    with patch.object(namespace["op"], "create_table") as create_table, patch.object(
        namespace["op"], "create_index"
    ) as create_index:
        namespace["upgrade"]()

    assert [call.args[0] for call in create_table.call_args_list] == [
        "workflow_run_steps",
        "workflow_trace_events",
    ]
    step_columns = {column.name: column for column in create_table.call_args_list[0].args[1:] if hasattr(column, "name")}
    trace_columns = {column.name: column for column in create_table.call_args_list[1].args[1:] if hasattr(column, "name")}
    assert next(iter(step_columns["run_id"].foreign_keys)).target_fullname == "workflow_runs.id"
    assert next(iter(trace_columns["step_id"].foreign_keys)).target_fullname == "workflow_run_steps.id"
    assert [call.args[0] for call in create_index.call_args_list] == [
        "workflow_trace_events_run_id_created_at_idx",
        "workflow_trace_events_step_id_idx",
    ]

    with patch.object(namespace["op"], "drop_table") as drop_table, patch.object(
        namespace["op"], "drop_index"
    ):
        namespace["downgrade"]()

    assert [call.args[0] for call in drop_table.call_args_list] == [
        "workflow_trace_events",
        "workflow_run_steps",
    ]
