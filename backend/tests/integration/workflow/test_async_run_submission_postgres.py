"""Real PostgreSQL proofs for async workflow-run submission transactions."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.exceptions import ExternalServiceError, NotFoundError
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun
from app.db.models.workflow import WorkflowCheckpoint as DBCheckpoint
from app.db.models.workspace import Workspace
from app.repositories import workspace as workspace_repo
from app.schemas.workflow import WorkflowCreate, WorkflowGraphSchema
from app.services.workflow import WorkflowAsyncRunService, WorkflowService
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspaceRole

DATABASE = "agentforge_v09_atomic5_verify"


@dataclass
class SubmissionData:
    workspace_id: UUID
    workflow_id: UUID
    users: dict[str, UUID]


class RecordingDispatcher:
    def __init__(self, factory, *, failure: Exception | None = None) -> None:
        self.factory = factory
        self.failure = failure
        self.jobs = []
        self.observed = []

    async def dispatch(self, job) -> None:
        self.jobs.append(job)
        async with self.factory() as observer:
            self.observed.append(await observer.get(WorkflowRun, job.run_id))
        if self.failure is not None:
            raise self.failure


def workflow_create() -> WorkflowCreate:
    return WorkflowCreate(
        name="Atomic 5 async submission",
        definition=WorkflowGraphSchema(
            entry_node_id="start",
            nodes=[
                {"id": "start", "kind": "start"},
                {"id": "value", "kind": "value", "config": {"value": "original"}},
                {"id": "end", "kind": "end"},
            ],
            edges=[
                {"id": "start-value", "source": "start", "target": "value"},
                {"id": "value-end", "source": "value", "target": "end"},
            ],
            metadata={"version": "original"},
        ),
    )


@pytest.fixture
async def submission_data(postgres_restart_session_factory) -> AsyncIterator[SubmissionData]:
    if settings.POSTGRES_DB != DATABASE:
        pytest.skip(f"Async submission proof requires POSTGRES_DB={DATABASE}.")
    factory = postgres_restart_session_factory
    users = {name: uuid4() for name in ("owner", "admin", "member", "outsider")}
    workspace_id = uuid4()
    async with factory() as db:
        db.add_all(
            [
                User(
                    id=user_id,
                    email=f"atomic5-{name}-{user_id.hex}@example.invalid",
                    hashed_password=None,
                )
                for name, user_id in users.items()
            ]
        )
        await db.flush()
        workspace = await workspace_repo.create_workspace(
            db,
            workspace_id=workspace_id,
            name="Atomic 5 proof",
            created_by_user_id=users["owner"],
        )
        for name, role in (
            ("owner", WorkspaceRole.OWNER),
            ("admin", WorkspaceRole.ADMIN),
            ("member", WorkspaceRole.MEMBER),
        ):
            await workspace_repo.create_membership(
                db,
                workspace_id=workspace.id,
                user_id=users[name],
                role=role,
            )
        workflow = await WorkflowService(db, WorkspaceAuthorizationService(db)).create_workflow(
            workspace.id, users["owner"], workflow_create()
        )
        await db.commit()
    try:
        yield SubmissionData(workspace_id, workflow.id, users)
    finally:
        async with factory() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.execute(delete(User).where(User.id.in_(users.values())))
            await db.commit()


def async_service(db, dispatcher) -> WorkflowAsyncRunService:
    return WorkflowAsyncRunService(
        db,
        WorkflowService(db, WorkspaceAuthorizationService(db)),
        dispatcher,
    )


@pytest.mark.anyio
async def test_commit_is_visible_before_dispatch_and_snapshot_is_immutable(
    postgres_restart_session_factory, submission_data
) -> None:
    factory = postgres_restart_session_factory
    dispatcher = RecordingDispatcher(factory)
    async with factory() as db:
        created = await async_service(db, dispatcher).submit_workflow(
            submission_data.workflow_id,
            submission_data.users["owner"],
            {"nested": {"value": 1}},
        )
        run_id = created.id

    assert dispatcher.observed[0] is not None
    observed = dispatcher.observed[0]
    assert observed.status == "pending"
    assert observed.started_at is observed.finished_at is None
    assert observed.node_outputs == {}
    assert observed.output is observed.error is None
    assert observed.execution_claim_token is observed.execution_lease_expires_at is None
    assert observed.execution_claim_generation == 0

    async with factory() as db:
        await db.execute(
            update(Workflow)
            .where(Workflow.id == submission_data.workflow_id)
            .values(
                revision=2,
                definition={
                    "schema_version": 1,
                    "entry_node_id": "start",
                    "nodes": [],
                    "edges": [],
                    "metadata": {"version": "changed"},
                },
            )
        )
        await db.commit()
    async with factory() as db:
        stored = await db.get(WorkflowRun, run_id)
        assert stored is not None
        assert stored.workflow_revision == 1
        assert stored.definition_snapshot["metadata"] == {"version": "original"}
        assert stored.input == {"nested": {"value": 1}}


@pytest.mark.anyio
async def test_publish_failure_retains_committed_pending_run(
    postgres_restart_session_factory, submission_data
) -> None:
    factory = postgres_restart_session_factory
    dispatcher = RecordingDispatcher(factory, failure=ConnectionError("broker timeout"))
    async with factory() as db:
        with pytest.raises(ExternalServiceError) as captured:
            await async_service(db, dispatcher).submit_workflow(
                submission_data.workflow_id,
                submission_data.users["admin"],
                {},
            )
    run_id = UUID(captured.value.details["run_id"])
    async with factory() as db:
        stored = await db.get(WorkflowRun, run_id)
        assert stored is not None
        assert stored.status == "pending"
        assert stored.execution_claim_token is stored.execution_lease_expires_at is None
        assert stored.execution_claim_generation == 0
        assert (
            await db.scalar(
                select(func.count()).select_from(DBCheckpoint).where(DBCheckpoint.run_id == run_id)
            )
            == 0
        )


@pytest.mark.anyio
async def test_real_database_write_failure_never_dispatches_or_partially_commits(
    postgres_restart_session_factory, submission_data
) -> None:
    factory = postgres_restart_session_factory
    dispatcher = RecordingDispatcher(factory)
    async with factory() as db:
        authorized = WorkflowService(db, WorkspaceAuthorizationService(db))

        class DeleteAfterAuthorization:
            async def get_authorized_workflow(self, *args, **kwargs):
                row = await authorized.get_authorized_workflow(*args, **kwargs)
                async with factory() as deleting:
                    await deleting.execute(
                        delete(Workspace).where(Workspace.id == submission_data.workspace_id)
                    )
                    await deleting.commit()
                return row

        with pytest.raises(IntegrityError):
            await WorkflowAsyncRunService(
                db, DeleteAfterAuthorization(), dispatcher
            ).submit_workflow(
                submission_data.workflow_id,
                submission_data.users["member"],
                {},
            )
    assert dispatcher.jobs == []
    async with factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(WorkflowRun)
                .where(WorkflowRun.workflow_id == submission_data.workflow_id)
            )
            == 0
        )


@pytest.mark.anyio
async def test_owner_admin_member_are_allowed_and_outsider_is_hidden(
    postgres_restart_session_factory, submission_data
) -> None:
    factory = postgres_restart_session_factory
    dispatcher = RecordingDispatcher(factory)
    for role in ("owner", "admin", "member"):
        async with factory() as db:
            await async_service(db, dispatcher).submit_workflow(
                submission_data.workflow_id,
                submission_data.users[role],
                {"role": role},
            )
    async with factory() as db:
        with pytest.raises(NotFoundError):
            await async_service(db, dispatcher).submit_workflow(
                submission_data.workflow_id,
                submission_data.users["outsider"],
                {},
            )
    assert len(dispatcher.jobs) == 3
