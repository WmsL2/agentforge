"""Static tests for the workspace Alembic migration."""

import runpy
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import CheckConstraint

MIGRATION = Path(__file__).parents[3] / "alembic" / "versions" / "0038_create_workspaces.py"


def test_workspace_migration_has_the_required_revision_chain() -> None:
    namespace = runpy.run_path(str(MIGRATION))

    assert namespace["revision"] == "0038_create_workspaces"
    assert namespace["down_revision"] == "0037_create_workflow_observability"


def test_workspace_migration_creates_and_drops_tables_in_dependency_order() -> None:
    namespace = runpy.run_path(str(MIGRATION))
    with patch.object(namespace["op"], "create_table") as create_table, patch.object(
        namespace["op"], "create_index"
    ) as create_index:
        namespace["upgrade"]()

    assert [call.args[0] for call in create_table.call_args_list] == ["workspaces", "workspace_memberships"]
    workspaces = {column.name: column for column in create_table.call_args_list[0].args[1:] if hasattr(column, "name")}
    memberships = {column.name: column for column in create_table.call_args_list[1].args[1:] if hasattr(column, "name")}
    creator_fk = next(iter(workspaces["created_by_user_id"].foreign_keys))
    workspace_fk = next(iter(memberships["workspace_id"].foreign_keys))
    user_fk = next(iter(memberships["user_id"].foreign_keys))
    assert (creator_fk.target_fullname, creator_fk.ondelete) == ("users.id", "SET NULL")
    assert (workspace_fk.target_fullname, workspace_fk.ondelete) == ("workspaces.id", "CASCADE")
    assert (user_fk.target_fullname, user_fk.ondelete) == ("users.id", "CASCADE")
    assert memberships["workspace_id"].primary_key is True
    assert memberships["user_id"].primary_key is True
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.sqltext.text == "role IN ('owner', 'admin', 'member')"
        for constraint in create_table.call_args_list[1].args[1:]
    )
    assert [call.args[0] for call in create_index.call_args_list] == ["workspace_memberships_user_id_idx"]

    with patch.object(namespace["op"], "drop_table") as drop_table, patch.object(
        namespace["op"], "drop_index"
    ):
        namespace["downgrade"]()

    assert [call.args[0] for call in drop_table.call_args_list] == ["workspace_memberships", "workspaces"]
