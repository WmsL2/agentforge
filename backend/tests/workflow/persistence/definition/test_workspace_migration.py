"""Static contract tests for workflow workspace migration and ORM fields."""

import runpy
from pathlib import Path
from uuid import uuid4

from app.db.models.workflow.definition.model import Workflow

MIGRATION = Path(__file__).parents[4] / "alembic" / "versions" / "0039_add_workflow_workspace_scope.py"


def test_workflow_orm_uses_nullable_workspace_scope_and_creator_provenance() -> None:
    table = Workflow.__table__
    workspace_fk = next(iter(table.c.workspace_id.foreign_keys))
    user_fk = next(iter(table.c.user_id.foreign_keys))

    assert table.c.workspace_id.nullable is True
    assert (workspace_fk.target_fullname, workspace_fk.ondelete) == ("workspaces.id", "CASCADE")
    assert table.c.user_id.nullable is True
    assert (user_fk.target_fullname, user_fk.ondelete) == ("users.id", "SET NULL")
    assert {tuple(index.columns.keys()) for index in table.indexes} >= {("user_id",), ("workspace_id",)}


def test_workspace_scope_migration_has_expected_revision_and_stable_personal_ids() -> None:
    namespace = runpy.run_path(str(MIGRATION))
    first, second = uuid4(), uuid4()

    assert namespace["revision"] == "0039_add_workflow_workspace_scope"
    assert namespace["down_revision"] == "0038_create_workspaces"
    assert namespace["personal_workspace_id"](first) == namespace["personal_workspace_id"](first)
    assert namespace["personal_workspace_id"](first) != namespace["personal_workspace_id"](second)


def test_workspace_scope_migration_declares_upgrade_and_downgrade_semantics() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "workflows_workspace_id_fkey" in source
    assert "workflows_workspace_id_idx" in source
    assert 'ondelete="CASCADE"' in source
    assert 'ondelete="SET NULL"' in source
    assert "Personal Workspace" in source
    assert "on_conflict_do_nothing" in source
    assert "workflows.c.workspace_id.is_(None)" in source
    assert "nullable=False" in source
    assert "op.drop_column(\"workflows\", \"workspace_id\")" in source
