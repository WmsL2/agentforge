"""Static and mocked persistence tests for the Knowledge Base domain."""

import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import UniqueConstraint

from app.db.models.knowledge import KnowledgeBase
from app.repositories import knowledge as knowledge_repo

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0043_create_knowledge_bases.py"


def test_model_has_workspace_scope_constraints_and_indexes() -> None:
    table = KnowledgeBase.__table__
    assert set(table.columns) == {
        table.c.id,
        table.c.workspace_id,
        table.c.name,
        table.c.description,
        table.c.created_by_user_id,
        table.c.created_at,
        table.c.updated_at,
    }
    assert table.c.name.type.length == 255
    assert table.c.description.nullable is True
    workspace_fk = next(iter(table.c.workspace_id.foreign_keys))
    creator_fk = next(iter(table.c.created_by_user_id.foreign_keys))
    assert (workspace_fk.target_fullname, workspace_fk.ondelete) == (
        "workspaces.id",
        "CASCADE",
    )
    assert (creator_fk.target_fullname, creator_fk.ondelete) == ("users.id", "SET NULL")
    assert any(
        isinstance(constraint, UniqueConstraint)
        and tuple(constraint.columns.keys()) == ("workspace_id", "name")
        for constraint in table.constraints
    )
    assert {tuple(index.columns.keys()) for index in table.indexes} == {
        ("workspace_id", "created_at", "id")
    }


def test_migration_creates_and_drops_exact_contract() -> None:
    namespace = runpy.run_path(str(MIGRATION))
    assert namespace["revision"] == "0043_create_knowledge_bases"
    assert namespace["down_revision"] == "0042_add_workflow_recovery_dispatch_schedule"
    with (
        patch.object(namespace["op"], "create_table") as create_table,
        patch.object(namespace["op"], "create_index") as create_index,
    ):
        namespace["upgrade"]()
    assert create_table.call_args.args[0] == "knowledge_bases"
    assert create_index.call_args.args == (
        "knowledge_bases_workspace_created_id_idx",
        "knowledge_bases",
        ["workspace_id", "created_at", "id"],
    )
    with (
        patch.object(namespace["op"], "drop_index") as drop_index,
        patch.object(namespace["op"], "drop_table") as drop_table,
    ):
        namespace["downgrade"]()
    drop_index.assert_called_once_with(
        "knowledge_bases_workspace_created_id_idx", table_name="knowledge_bases"
    )
    drop_table.assert_called_once_with("knowledge_bases")


@pytest.mark.anyio
async def test_repository_writes_flush_without_committing_and_queries_are_scoped() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = [SimpleNamespace()]
    db.execute.return_value = result
    workspace_id, actor_id, knowledge_base_id = uuid4(), uuid4(), uuid4()

    created = await knowledge_repo.create(
        db,
        workspace_id=workspace_id,
        name="Research",
        description=None,
        created_by_user_id=actor_id,
    )
    assert created.workspace_id == workspace_id
    await knowledge_repo.get_by_workspace_and_id(
        db, workspace_id=workspace_id, knowledge_base_id=knowledge_base_id
    )
    scoped_statement = str(db.execute.await_args.args[0])
    assert "knowledge_bases.workspace_id" in scoped_statement
    assert "knowledge_bases.id" in scoped_statement
    rows = await knowledge_repo.list_by_workspace(db, workspace_id=workspace_id, skip=0, limit=10)
    assert len(rows) == 1
    list_statement = str(db.execute.await_args.args[0])
    assert "ORDER BY knowledge_bases.created_at ASC, knowledge_bases.id ASC" in list_statement
    await knowledge_repo.update(
        db, db_knowledge_base=created, update_data={"description": "Updated"}
    )
    await knowledge_repo.delete(db, db_knowledge_base=created)
    assert db.flush.await_count == 3
    db.commit.assert_not_awaited()
