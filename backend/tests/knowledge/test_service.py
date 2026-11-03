"""Unit tests for Knowledge Base service validation, RBAC, and transactions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.schemas.knowledge import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.knowledge.service import KnowledgeBaseService
from app.services.workspace.domain import WorkspacePermission


def make_service() -> tuple[KnowledgeBaseService, AsyncMock, AsyncMock]:
    db = AsyncMock()
    authorization = AsyncMock()
    return KnowledgeBaseService(db, authorization), db, authorization


@pytest.mark.anyio
async def test_create_requires_create_permission_and_uses_authenticated_actor() -> None:
    service, db, authorization = make_service()
    workspace_id, actor_id = uuid4(), uuid4()
    created = SimpleNamespace(id=uuid4())
    with (
        patch(
            "app.services.knowledge.service.knowledge_repo.get_by_workspace_and_name",
            AsyncMock(return_value=None),
        ) as get_by_name,
        patch(
            "app.services.knowledge.service.knowledge_repo.create",
            AsyncMock(return_value=created),
        ) as create,
    ):
        result = await service.create_knowledge_base(
            workspace_id,
            actor_id,
            KnowledgeBaseCreate(name="  Research  ", description="Notes"),
        )

    assert result is created
    authorization.require_permission.assert_awaited_once_with(
        workspace_id, actor_id, WorkspacePermission.KNOWLEDGE_CREATE
    )
    get_by_name.assert_awaited_once_with(db, workspace_id=workspace_id, name="Research")
    create.assert_awaited_once_with(
        db,
        workspace_id=workspace_id,
        name="Research",
        description="Notes",
        created_by_user_id=actor_id,
    )
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_permission_rejection_prevents_create_and_delete_writes() -> None:
    service, _, authorization = make_service()
    authorization.require_permission.side_effect = AuthorizationError(message="denied")
    with (
        patch("app.services.knowledge.service.knowledge_repo.create", AsyncMock()) as create,
        patch("app.services.knowledge.service.knowledge_repo.delete", AsyncMock()) as delete,
    ):
        with pytest.raises(AuthorizationError):
            await service.create_knowledge_base(
                uuid4(), uuid4(), KnowledgeBaseCreate(name="Denied")
            )
        with pytest.raises(AuthorizationError):
            await service.delete_knowledge_base(uuid4(), uuid4(), uuid4())
    create.assert_not_awaited()
    delete.assert_not_awaited()


@pytest.mark.anyio
async def test_list_and_get_are_workspace_scoped_and_use_read_permission() -> None:
    service, db, authorization = make_service()
    workspace_id, actor_id, knowledge_base_id = uuid4(), uuid4(), uuid4()
    row = SimpleNamespace(id=knowledge_base_id)
    with (
        patch(
            "app.services.knowledge.service.knowledge_repo.list_by_workspace",
            AsyncMock(return_value=[row]),
        ) as list_by_workspace,
        patch(
            "app.services.knowledge.service.knowledge_repo.count_by_workspace",
            AsyncMock(return_value=1),
        ) as count,
        patch(
            "app.services.knowledge.service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=row),
        ) as get_by_id,
    ):
        assert await service.list_knowledge_bases(workspace_id, actor_id, skip=5, limit=10) == (
            [row],
            1,
        )
        assert await service.get_knowledge_base(workspace_id, knowledge_base_id, actor_id) is row

    assert authorization.require_permission.await_args_list[0].args == (
        workspace_id,
        actor_id,
        WorkspacePermission.KNOWLEDGE_READ,
    )
    list_by_workspace.assert_awaited_once_with(db, workspace_id=workspace_id, skip=5, limit=10)
    count.assert_awaited_once_with(db, workspace_id=workspace_id)
    get_by_id.assert_awaited_once_with(
        db, workspace_id=workspace_id, knowledge_base_id=knowledge_base_id
    )


@pytest.mark.anyio
async def test_missing_or_cross_workspace_resource_is_not_found() -> None:
    service, _, _ = make_service()
    with (
        patch(
            "app.services.knowledge.service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=None),
        ),
        pytest.raises(NotFoundError) as error,
    ):
        await service.get_knowledge_base(uuid4(), uuid4(), uuid4())
    assert error.value.message == "Knowledge base not found"


@pytest.mark.anyio
async def test_update_supports_empty_patch_and_explicit_null_description() -> None:
    service, db, authorization = make_service()
    workspace_id, actor_id, knowledge_base_id = uuid4(), uuid4(), uuid4()
    row = SimpleNamespace(id=knowledge_base_id, name="Existing", description="Old")
    with (
        patch(
            "app.services.knowledge.service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.services.knowledge.service.knowledge_repo.update",
            AsyncMock(return_value=row),
        ) as update,
    ):
        assert (
            await service.update_knowledge_base(
                workspace_id, knowledge_base_id, actor_id, KnowledgeBaseUpdate()
            )
            is row
        )
        update.assert_not_awaited()
        assert (
            await service.update_knowledge_base(
                workspace_id,
                knowledge_base_id,
                actor_id,
                KnowledgeBaseUpdate(description=None),
            )
            is row
        )

    update.assert_awaited_once_with(db, db_knowledge_base=row, update_data={"description": None})
    assert authorization.require_permission.await_args.args[2] is WorkspacePermission.KNOWLEDGE_EDIT
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_duplicate_name_is_rejected_before_update_or_create() -> None:
    service, _, _ = make_service()
    row = SimpleNamespace(id=uuid4(), name="First")
    duplicate = SimpleNamespace(id=uuid4(), name="Second")
    with (
        patch(
            "app.services.knowledge.service.knowledge_repo.get_by_workspace_and_name",
            AsyncMock(return_value=duplicate),
        ),
        pytest.raises(AlreadyExistsError),
    ):
        await service.create_knowledge_base(uuid4(), uuid4(), KnowledgeBaseCreate(name="Second"))
    with (
        patch(
            "app.services.knowledge.service.knowledge_repo.get_by_workspace_and_id",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.services.knowledge.service.knowledge_repo.get_by_workspace_and_name",
            AsyncMock(return_value=duplicate),
        ),
        patch("app.services.knowledge.service.knowledge_repo.update", AsyncMock()) as update,
        pytest.raises(AlreadyExistsError),
    ):
        await service.update_knowledge_base(
            uuid4(), row.id, uuid4(), KnowledgeBaseUpdate(name="Second")
        )
    update.assert_not_awaited()


class _UniqueViolation(Exception):
    diag = SimpleNamespace(constraint_name="knowledge_bases_workspace_id_name_key")


@pytest.mark.anyio
async def test_database_unique_race_maps_to_conflict_without_service_rollback() -> None:
    service, db, _ = make_service()
    integrity_error = IntegrityError("insert", {}, _UniqueViolation())
    with (
        patch(
            "app.services.knowledge.service.knowledge_repo.get_by_workspace_and_name",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.knowledge.service.knowledge_repo.create",
            AsyncMock(side_effect=integrity_error),
        ),
        pytest.raises(AlreadyExistsError),
    ):
        await service.create_knowledge_base(uuid4(), uuid4(), KnowledgeBaseCreate(name="Race"))
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


def test_name_validation_strips_whitespace_and_rejects_invalid_values() -> None:
    assert KnowledgeBaseCreate(name="  valid  ").name == "valid"
    for value in ("", "   ", "x" * 256):
        with pytest.raises(PydanticValidationError):
            KnowledgeBaseCreate(name=value)
    with pytest.raises(PydanticValidationError):
        KnowledgeBaseUpdate(name=None)
