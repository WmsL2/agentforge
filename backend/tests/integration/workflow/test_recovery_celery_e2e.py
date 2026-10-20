"""Atomic 6 real PostgreSQL -> Redis -> Celery recovery acceptance tests."""

import asyncio
import os
import subprocess
import sys
import time
from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from celery import Celery
from httpx import ASGITransport, AsyncClient
from redis import Redis
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_tool_registry, get_workflow_execution_dispatcher
from app.core.config import settings
from app.core.security import create_access_token
from app.db.models.user import User
from app.db.models.workflow import ApprovalRequest, Workflow, WorkflowCheckpoint, WorkflowRun
from app.db.models.workspace import Workspace
from app.integrations.celery.workflow_dispatcher import CeleryWorkflowDispatcher
from app.main import app
from app.repositories import workspace as workspace_repo
from app.services.tool import ToolRegistry
from app.services.workflow import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowRecoveryScanner,
    serialize_workflow_graph,
)
from app.services.workspace.domain import WorkspaceRole
from app.worker.celery_app import celery_app

DATABASE = "agentforge_v09_atomic6_verify"
HEAD = "0042_add_workflow_recovery_dispatch_schedule"
BACKEND_ROOT = Path(__file__).parents[3]


def _definition(*, approval: bool = False) -> WorkflowDefinition:
    nodes = [WorkflowNode("start", WorkflowNodeKind.START)]
    if approval:
        nodes.extend(
            [
                WorkflowNode("approval", WorkflowNodeKind.APPROVAL, config={"prompt": "Continue?"}),
                WorkflowNode(
                    "after", WorkflowNodeKind.VALUE, config={"value": "atomic-6-approval"}
                ),
            ]
        )
    else:
        nodes.append(WorkflowNode("value", WorkflowNodeKind.VALUE, config={"value": "atomic-6"}))
    nodes.append(WorkflowNode("end", WorkflowNodeKind.END))
    return WorkflowDefinition(
        uuid4(),
        "Atomic 6 E2E",
        "start",
        nodes=tuple(nodes),
        edges=tuple(
            WorkflowEdge(f"{source.id}-{target.id}", source.id, target.id)
            for source, target in pairwise(nodes)
        ),
    )


def _require_atomic6_environment() -> None:
    if os.getenv("AGENTFORGE_RUN_ATOMIC6_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_ATOMIC6_E2E=1 for Atomic 6 E2E.")
    if os.getenv("AGENTFORGE_RUN_POSTGRES_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_POSTGRES_E2E=1 for Atomic 6 E2E.")
    if settings.POSTGRES_DB != DATABASE:
        pytest.fail(f"Atomic 6 E2E requires POSTGRES_DB={DATABASE}.")


def _ping_redis() -> None:
    client = Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2, socket_timeout=2)
    try:
        client.ping()
    finally:
        client.close()


async def _wait_worker(hostname: str, worker: subprocess.Popen) -> list[str]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            pytest.fail(f"Atomic 6 Celery worker exited during startup ({worker.returncode}).")
        registered = await asyncio.to_thread(
            celery_app.control.inspect(destination=[hostname], timeout=1).registered
        )
        if registered and hostname in registered:
            return registered[hostname]
        await asyncio.sleep(0.25)
    pytest.fail("Atomic 6 Celery worker did not become ready within 30 seconds.")


async def _wait_completed(factory: async_sessionmaker[AsyncSession], run_id: UUID) -> WorkflowRun:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        async with factory() as db:
            run = await db.get(WorkflowRun, run_id)
        if run is not None and run.status == "completed":
            return run
        await asyncio.sleep(0.1)
    pytest.fail(f"Atomic 6 run {run_id} did not complete.")


class _Publisher:
    def __init__(self, app: Celery) -> None:
        self._app = app
        self.results = []

    def send_task(self, name: str, *, kwargs: dict[str, str]):
        result = self._app.send_task(name, kwargs=kwargs)
        self.results.append(result)
        return result


@pytest.fixture
async def atomic6_worker():
    _require_atomic6_environment()
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    worker = None
    old_queue = celery_app.conf.task_default_queue
    try:
        try:
            async with engine.connect() as connection:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            await asyncio.to_thread(_ping_redis)
        except Exception as error:
            pytest.fail(f"Atomic 6 PostgreSQL or Redis is unavailable: {type(error).__name__}.")
        if revision != HEAD:
            pytest.fail(f"Atomic 6 PostgreSQL must be at {HEAD}; found {revision!r}.")
        queue = f"agentforge-atomic6-{uuid4().hex}"
        hostname = f"atomic6-{uuid4().hex}@localhost"
        celery_app.conf.task_default_queue = queue
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "app.worker.celery_app:celery_app",
                "worker",
                "--pool=solo",
                "--loglevel=INFO",
                "--queues",
                queue,
                "--hostname",
                hostname,
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
            ],
            cwd=BACKEND_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        registered = await _wait_worker(hostname, worker)
        yield async_sessionmaker(engine, expire_on_commit=False), _Publisher(celery_app), registered
    finally:
        celery_app.conf.task_default_queue = old_queue
        if worker is not None:
            worker.terminate()
            try:
                await asyncio.to_thread(worker.wait, 10)
            except subprocess.TimeoutExpired:
                worker.kill()
                await asyncio.to_thread(worker.wait, 5)
        await engine.dispose()


async def _create_pending(factory: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    workspace_id, run_id = uuid4(), uuid4()
    definition = _definition()
    async with factory() as db:
        db.add(Workspace(id=workspace_id, name="Atomic 6 worker"))
        await db.flush()
        db.add(
            Workflow(
                id=definition.id,
                workspace_id=workspace_id,
                name=definition.name,
                definition=serialize_workflow_graph(definition),
                revision=1,
            )
        )
        await db.flush()
        db.add(
            WorkflowRun(
                id=run_id,
                workflow_id=definition.id,
                workflow_revision=1,
                definition_snapshot=serialize_workflow_graph(definition),
                status="pending",
                input={"source": "atomic6-scanner"},
            )
        )
        await db.flush()
        await db.commit()
    return workspace_id, run_id


@pytest.mark.anyio
async def test_scanner_dispatches_through_redis_to_real_worker(atomic6_worker) -> None:
    factory, publisher, registered = atomic6_worker
    workspace_id, run_id = await _create_pending(factory)
    try:
        assert "agentforge.workflow.execute" in registered
        assert "agentforge.workflow.recovery.scan" in registered
        scanner = WorkflowRecoveryScanner(
            factory,
            CeleryWorkflowDispatcher(publisher),
            batch_size=10,
            redispatch_delay=timedelta(seconds=60),
        )
        result = await scanner.scan_once()
        assert (result.scanned, result.dispatched, result.failed) == (1, 1, 0)
        task = publisher.results[0]
        outcome = await asyncio.to_thread(task.get, timeout=30, propagate=True)
        assert outcome["status"] == "completed" and outcome["lease_released"] is True
        stored = await _wait_completed(factory, run_id)
        assert stored.output == {"end": {"value": "atomic-6"}}
        assert stored.execution_claim_token is None and stored.execution_lease_expires_at is None
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(WorkflowCheckpoint)
                    .where(WorkflowCheckpoint.run_id == run_id)
                )
                == 3
            )
    finally:
        async with factory() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.commit()


@pytest.mark.anyio
async def test_async_approval_http_reaches_real_worker(atomic6_worker) -> None:
    factory, _, _ = atomic6_worker
    user_id, workspace_id, run_id, approval_id = uuid4(), uuid4(), uuid4(), uuid4()
    definition = _definition(approval=True)
    try:
        async with factory() as db:
            db.add(
                User(
                    id=user_id,
                    email=f"atomic6-{user_id.hex}@example.invalid",
                    hashed_password=None,
                )
            )
            await db.flush()
            workspace = await workspace_repo.create_workspace(
                db, workspace_id=workspace_id, name="Atomic 6 approval", created_by_user_id=user_id
            )
            await workspace_repo.create_membership(
                db, workspace_id=workspace.id, user_id=user_id, role=WorkspaceRole.OWNER
            )
            db.add(
                Workflow(
                    id=definition.id,
                    user_id=user_id,
                    workspace_id=workspace.id,
                    name=definition.name,
                    definition=serialize_workflow_graph(definition),
                    revision=1,
                )
            )
            await db.flush()
            db.add(
                WorkflowRun(
                    id=run_id,
                    workflow_id=definition.id,
                    workflow_revision=1,
                    definition_snapshot=serialize_workflow_graph(definition),
                    status="paused",
                    input={"source": "atomic6-approval"},
                    node_outputs={"start": {}},
                )
            )
            await db.flush()
            db.add(
                ApprovalRequest(
                    id=approval_id,
                    run_id=run_id,
                    workflow_revision=1,
                    node_id="approval",
                    prompt="Continue?",
                    status="pending",
                )
            )
            db.add(
                WorkflowCheckpoint(
                    id=uuid4(),
                    run_id=run_id,
                    workflow_revision=1,
                    sequence=1,
                    completed_node_ids=["start"],
                    node_outputs={"start": {}},
                    pending_node_id="approval",
                    interrupt={
                        "type": "approval_required",
                        "payload": {"node_id": "approval", "prompt": "Continue?"},
                    },
                )
            )
            await db.commit()
        app.dependency_overrides[get_tool_registry] = ToolRegistry
        headers = {"Authorization": f"Bearer {create_access_token(user_id)}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workflows/{definition.id}/runs/{run_id}/approvals/{approval_id}/approve/async",
                json={"note": "approved"},
                headers=headers,
            )
        assert response.status_code == 202
        assert response.headers["location"] == f"/api/v1/workflows/{definition.id}/runs/{run_id}"
        stored = await _wait_completed(factory, run_id)
        assert stored.output == {"end": {"value": "atomic-6-approval"}}
        async with factory() as db:
            approval = await db.get(ApprovalRequest, approval_id)
            count = await db.scalar(
                select(func.count())
                .select_from(WorkflowCheckpoint)
                .where(WorkflowCheckpoint.run_id == run_id)
            )
        assert approval is not None and approval.status == "approved"
        assert count == 4
    finally:
        app.dependency_overrides.clear()
        async with factory() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


@pytest.mark.anyio
async def test_async_approval_publish_failure_commits_then_scanner_recovers(atomic6_worker) -> None:
    class FailingDispatcher:
        async def dispatch(self, _job) -> None:
            raise ConnectionError("injected initial publish failure")

    factory, publisher, _ = atomic6_worker
    user_id, workspace_id, run_id, approval_id = uuid4(), uuid4(), uuid4(), uuid4()
    definition = _definition(approval=True)
    try:
        async with factory() as db:
            db.add(
                User(
                    id=user_id,
                    email=f"atomic6-failure-{user_id.hex}@example.invalid",
                    hashed_password=None,
                )
            )
            await db.flush()
            workspace = await workspace_repo.create_workspace(
                db,
                workspace_id=workspace_id,
                name="Atomic 6 approval publish failure",
                created_by_user_id=user_id,
            )
            await workspace_repo.create_membership(
                db, workspace_id=workspace.id, user_id=user_id, role=WorkspaceRole.OWNER
            )
            db.add(
                Workflow(
                    id=definition.id,
                    user_id=user_id,
                    workspace_id=workspace.id,
                    name=definition.name,
                    definition=serialize_workflow_graph(definition),
                    revision=1,
                )
            )
            await db.flush()
            db.add(
                WorkflowRun(
                    id=run_id,
                    workflow_id=definition.id,
                    workflow_revision=1,
                    definition_snapshot=serialize_workflow_graph(definition),
                    status="paused",
                    input={"source": "atomic6-publish-failure"},
                    node_outputs={"start": {}},
                )
            )
            await db.flush()
            db.add(
                ApprovalRequest(
                    id=approval_id,
                    run_id=run_id,
                    workflow_revision=1,
                    node_id="approval",
                    prompt="Continue?",
                    status="pending",
                )
            )
            db.add(
                WorkflowCheckpoint(
                    id=uuid4(),
                    run_id=run_id,
                    workflow_revision=1,
                    sequence=1,
                    completed_node_ids=["start"],
                    node_outputs={"start": {}},
                    pending_node_id="approval",
                    interrupt={
                        "type": "approval_required",
                        "payload": {"node_id": "approval", "prompt": "Continue?"},
                    },
                )
            )
            await db.commit()

        app.dependency_overrides[get_tool_registry] = ToolRegistry
        app.dependency_overrides[get_workflow_execution_dispatcher] = FailingDispatcher
        headers = {"Authorization": f"Bearer {create_access_token(user_id)}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workflows/{definition.id}/runs/{run_id}/approvals/{approval_id}/approve/async",
                json={"note": "approved"},
                headers=headers,
            )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "WORKFLOW_DISPATCH_FAILED"
        app.dependency_overrides.pop(get_workflow_execution_dispatcher)
        async with factory() as db:
            run = await db.get(WorkflowRun, run_id)
            approval = await db.get(ApprovalRequest, approval_id)
            stored = list(
                (
                    await db.scalars(
                        select(WorkflowCheckpoint)
                        .where(WorkflowCheckpoint.run_id == run_id)
                        .order_by(WorkflowCheckpoint.sequence)
                    )
                ).all()
            )
        assert run is not None and run.status == "paused"
        assert approval is not None and approval.status == "approved"
        assert [checkpoint.sequence for checkpoint in stored] == [1, 2]
        assert stored[-1].pending_node_id is None and stored[-1].interrupt is None

        scanner = WorkflowRecoveryScanner(
            factory,
            CeleryWorkflowDispatcher(publisher),
            batch_size=10,
            redispatch_delay=timedelta(seconds=60),
        )
        scan = await scanner.scan_once()
        assert (scan.scanned, scan.dispatched, scan.failed) == (1, 1, 0)
        outcome = await asyncio.to_thread(publisher.results[-1].get, timeout=30, propagate=True)
        assert outcome["status"] == "completed" and outcome["lease_released"] is True
        completed = await _wait_completed(factory, run_id)
        assert completed.output == {"end": {"value": "atomic-6-approval"}}
        assert (
            completed.execution_claim_token is None and completed.execution_lease_expires_at is None
        )
        async with factory() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(WorkflowCheckpoint)
                .where(WorkflowCheckpoint.run_id == run_id)
            )
        assert count == 4
    finally:
        app.dependency_overrides.clear()
        async with factory() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
