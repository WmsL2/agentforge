"""Opt-in real PostgreSQL proofs for workspace-scoped knowledge bases."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.db.models.knowledge import KnowledgeBase
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.repositories import knowledge as knowledge_repo
from app.repositories import workspace as workspace_repo
from app.schemas.knowledge import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.knowledge import KnowledgeBaseService
from app.services.workspace import WorkspaceAuthorizationService, WorkspaceRole


async def _create_user(session, label: str) -> UUID:
    user_id = uuid4()
    session.add(
        User(
            id=user_id,
            email=f"knowledge-{label}-{user_id.hex}@example.invalid",
            hashed_password=None,
        )
    )
    await session.flush()
    return user_id


@pytest.mark.anyio
async def test_real_memberships_enforce_rbac_crud_and_workspace_isolation(
    postgres_session,
) -> None:
    users = {
        role: await _create_user(postgres_session, role)
        for role in ("owner", "admin", "member", "outsider")
    }
    workspace_a = await workspace_repo.create_workspace(
        postgres_session, name="Knowledge A", created_by_user_id=users["owner"]
    )
    workspace_b = await workspace_repo.create_workspace(
        postgres_session, name="Knowledge B", created_by_user_id=users["owner"]
    )
    for workspace in (workspace_a, workspace_b):
        await workspace_repo.create_membership(
            postgres_session,
            workspace_id=workspace.id,
            user_id=users["owner"],
            role=WorkspaceRole.OWNER,
        )
    for actor, role in (("admin", WorkspaceRole.ADMIN), ("member", WorkspaceRole.MEMBER)):
        await workspace_repo.create_membership(
            postgres_session,
            workspace_id=workspace_a.id,
            user_id=users[actor],
            role=role,
        )

    service = KnowledgeBaseService(
        postgres_session, WorkspaceAuthorizationService(postgres_session)
    )
    owner_row = await service.create_knowledge_base(
        workspace_a.id,
        users["owner"],
        KnowledgeBaseCreate(name="Shared name", description="Owner data"),
    )
    admin_row = await service.create_knowledge_base(
        workspace_a.id, users["admin"], KnowledgeBaseCreate(name="Admin data")
    )
    same_name_other_workspace = await service.create_knowledge_base(
        workspace_b.id, users["owner"], KnowledgeBaseCreate(name="Shared name")
    )
    assert same_name_other_workspace.workspace_id == workspace_b.id

    items, total = await service.list_knowledge_bases(
        workspace_a.id, users["member"], skip=0, limit=100
    )
    expected_order = sorted((owner_row, admin_row), key=lambda item: (item.created_at, item.id))
    assert [item.id for item in items] == [item.id for item in expected_order]
    assert total == 2
    assert (
        await service.get_knowledge_base(workspace_a.id, owner_row.id, users["member"])
    ).id == owner_row.id

    for operation in (
        service.create_knowledge_base(
            workspace_a.id, users["member"], KnowledgeBaseCreate(name="Denied")
        ),
        service.update_knowledge_base(
            workspace_a.id,
            owner_row.id,
            users["member"],
            KnowledgeBaseUpdate(name="Denied"),
        ),
        service.delete_knowledge_base(workspace_a.id, owner_row.id, users["member"]),
    ):
        with pytest.raises(AuthorizationError):
            await operation
    with pytest.raises(NotFoundError):
        await service.get_knowledge_base(workspace_a.id, owner_row.id, users["outsider"])
    with pytest.raises(NotFoundError):
        await service.get_knowledge_base(workspace_b.id, owner_row.id, users["owner"])
    with pytest.raises(AlreadyExistsError):
        await service.create_knowledge_base(
            workspace_a.id, users["admin"], KnowledgeBaseCreate(name="Shared name")
        )

    updated = await service.update_knowledge_base(
        workspace_a.id,
        owner_row.id,
        users["admin"],
        KnowledgeBaseUpdate(name="Renamed", description=None),
    )
    assert (updated.name, updated.description) == ("Renamed", None)
    await service.delete_knowledge_base(workspace_a.id, admin_row.id, users["admin"])
    assert (
        await knowledge_repo.get_by_workspace_and_id(
            postgres_session,
            workspace_id=workspace_a.id,
            knowledge_base_id=admin_row.id,
        )
        is None
    )


@pytest.mark.anyio
async def test_postgresql_enforces_unique_foreign_key_and_workspace_cascade(
    postgres_session,
) -> None:
    user_id = await _create_user(postgres_session, "constraints")
    workspace = await workspace_repo.create_workspace(
        postgres_session, name="Constraint workspace", created_by_user_id=user_id
    )
    first = await knowledge_repo.create(
        postgres_session,
        workspace_id=workspace.id,
        name="Unique",
        description=None,
        created_by_user_id=user_id,
    )

    savepoint = await postgres_session.begin_nested()
    with pytest.raises(IntegrityError):
        await knowledge_repo.create(
            postgres_session,
            workspace_id=workspace.id,
            name="Unique",
            description=None,
            created_by_user_id=user_id,
        )
    await savepoint.rollback()

    savepoint = await postgres_session.begin_nested()
    with pytest.raises(IntegrityError):
        await knowledge_repo.create(
            postgres_session,
            workspace_id=uuid4(),
            name="Invalid workspace",
            description=None,
            created_by_user_id=user_id,
        )
    await savepoint.rollback()

    first_id = first.id
    assert await postgres_session.get(KnowledgeBase, first_id) is not None
    await postgres_session.delete(workspace)
    await postgres_session.flush()
    postgres_session.expire_all()
    assert await postgres_session.get(KnowledgeBase, first_id) is None


@pytest.mark.anyio
async def test_committed_persistence_and_failed_transaction_leave_no_extra_rows(
    postgres_restart_session_factory,
) -> None:
    factory = postgres_restart_session_factory
    user_id, workspace_id = uuid4(), uuid4()
    try:
        async with factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"knowledge-commit-{user_id.hex}@example.invalid",
                    hashed_password=None,
                )
            )
            session.add(
                Workspace(
                    id=workspace_id,
                    name="Committed knowledge",
                    created_by_user_id=user_id,
                )
            )
            await session.flush()
            await knowledge_repo.create(
                session,
                workspace_id=workspace_id,
                name="Durable",
                description="Committed",
                created_by_user_id=user_id,
            )
            await session.commit()

        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeBase)
                    .where(KnowledgeBase.workspace_id == workspace_id)
                )
            ) == 1
            with pytest.raises(IntegrityError):
                await knowledge_repo.create(
                    session,
                    workspace_id=workspace_id,
                    name="Durable",
                    description="Must roll back",
                    created_by_user_id=user_id,
                )
            await session.rollback()

        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeBase)
                    .where(KnowledgeBase.workspace_id == workspace_id)
                )
            ) == 1
    finally:
        async with factory() as session:
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.anyio
async def test_concurrent_same_name_creates_map_database_race_to_one_conflict(
    postgres_restart_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_restart_session_factory
    user_id, workspace_id = uuid4(), uuid4()
    try:
        async with factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"knowledge-race-{user_id.hex}@example.invalid",
                    hashed_password=None,
                )
            )
            session.add(
                Workspace(
                    id=workspace_id,
                    name="Concurrent knowledge",
                    created_by_user_id=user_id,
                )
            )
            await session.flush()
            await workspace_repo.create_membership(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
                role=WorkspaceRole.OWNER,
            )
            await session.commit()

        original_lookup = knowledge_repo.get_by_workspace_and_name
        both_prechecks_complete = asyncio.Barrier(2)

        async def synchronized_lookup(session, *, workspace_id, name):
            existing = await original_lookup(session, workspace_id=workspace_id, name=name)
            if existing is None:
                await both_prechecks_complete.wait()
            return existing

        monkeypatch.setattr(knowledge_repo, "get_by_workspace_and_name", synchronized_lookup)

        async def create_once() -> str:
            async with factory() as session:
                service = KnowledgeBaseService(session, WorkspaceAuthorizationService(session))
                try:
                    await service.create_knowledge_base(
                        workspace_id,
                        user_id,
                        KnowledgeBaseCreate(name="Concurrent"),
                    )
                    await session.commit()
                    return "created"
                except AlreadyExistsError:
                    await session.rollback()
                    return "conflict"

        assert sorted(await asyncio.gather(create_once(), create_once())) == [
            "conflict",
            "created",
        ]
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeBase)
                    .where(
                        KnowledgeBase.workspace_id == workspace_id,
                        KnowledgeBase.name == "Concurrent",
                    )
                )
            ) == 1
    finally:
        async with factory() as session:
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
