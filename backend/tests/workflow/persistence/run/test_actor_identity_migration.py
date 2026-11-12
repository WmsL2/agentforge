"""Static contract for the additive trusted run-actor migration."""

import runpy
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.dialects.postgresql import UUID

MIGRATION = Path(__file__).parents[4] / "alembic/versions/0046_add_workflow_run_actor_identity.py"


def test_actor_identity_revision_chain() -> None:
    namespace = runpy.run_path(str(MIGRATION))
    assert namespace["revision"] == "0046_add_workflow_run_actor_identity"
    assert namespace["down_revision"] == "0045_create_knowledge_vector_index"


def test_actor_identity_upgrade_and_downgrade_structure() -> None:
    namespace = runpy.run_path(str(MIGRATION))
    op = namespace["op"]
    with (
        patch.object(op, "add_column") as add_column,
        patch.object(op, "create_foreign_key") as create_foreign_key,
        patch.object(op, "create_index") as create_index,
    ):
        namespace["upgrade"]()

    column = add_column.call_args.args[1]
    assert add_column.call_args.args[0] == "workflow_runs"
    assert column.name == "actor_user_id"
    assert isinstance(column.type, UUID) and column.type.as_uuid
    assert column.nullable
    create_foreign_key.assert_called_once_with(
        "workflow_runs_actor_user_id_fkey",
        "workflow_runs",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    create_index.assert_called_once_with(
        "ix_workflow_runs_actor_user_id", "workflow_runs", ["actor_user_id"]
    )

    with (
        patch.object(op, "drop_index") as drop_index,
        patch.object(op, "drop_constraint") as drop_constraint,
        patch.object(op, "drop_column") as drop_column,
    ):
        namespace["downgrade"]()
    drop_index.assert_called_once_with("ix_workflow_runs_actor_user_id", table_name="workflow_runs")
    drop_constraint.assert_called_once_with(
        "workflow_runs_actor_user_id_fkey", "workflow_runs", type_="foreignkey"
    )
    drop_column.assert_called_once_with("workflow_runs", "actor_user_id")
