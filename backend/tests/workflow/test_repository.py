"""Focused unit tests for workflow repository persistence primitives."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories import workflow as workflow_repo


@pytest.mark.anyio
async def test_create_workflow_preserves_explicit_resource_fields_and_graph_payload():
    db = AsyncMock()
    db.add = MagicMock()
    workflow_id = uuid4()
    user_id = uuid4()
    payload = {
        "schema_version": 1,
        "entry_node_id": "start",
        "nodes": [],
        "edges": [],
        "metadata": {},
    }

    created = await workflow_repo.create_workflow(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        name="Workflow",
        description="Description",
        definition=payload,
        revision=2,
    )

    assert created.id == workflow_id
    assert created.user_id == user_id
    assert created.definition == payload
    assert created.revision == 2
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)


@pytest.mark.anyio
async def test_get_and_delete_workflow_handle_missing_rows():
    db = AsyncMock()
    db.add = MagicMock()
    workflow_id = uuid4()
    db.get.return_value = None

    assert await workflow_repo.get_workflow_by_id(db, workflow_id) is None
    assert await workflow_repo.delete_workflow(db, workflow_id) is False
    db.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_list_and_count_workflows_are_owner_scoped():
    db = AsyncMock()
    owner_id = uuid4()
    rows = [MagicMock(), MagicMock()]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute.return_value = result
    db.scalar.return_value = 2

    assert await workflow_repo.list_workflows_by_user(db, owner_id) == rows
    assert await workflow_repo.count_workflows_by_user(db, owner_id) == 2


@pytest.mark.anyio
async def test_delete_existing_workflow_flushes_row_removal():
    db = AsyncMock()
    stored = MagicMock()
    db.get.return_value = stored

    assert await workflow_repo.delete_workflow(db, uuid4()) is True
    db.delete.assert_awaited_once_with(stored)
    db.flush.assert_awaited_once()


@pytest.mark.anyio
async def test_update_workflow_persists_name_description_definition_and_revision():
    db = AsyncMock()
    db.add = MagicMock()
    stored = type(
        "StoredWorkflow", (), {"name": "Old", "description": None, "definition": {}, "revision": 1}
    )()
    payload = {
        "schema_version": 1,
        "entry_node_id": "start",
        "nodes": [],
        "edges": [],
        "metadata": {},
    }

    updated = await workflow_repo.update_workflow(
        db,
        db_workflow=stored,
        update_data={"name": "New", "description": "Updated", "definition": payload, "revision": 2},
    )

    assert updated is stored
    assert (stored.name, stored.description, stored.definition, stored.revision) == (
        "New",
        "Updated",
        payload,
        2,
    )
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(stored)
