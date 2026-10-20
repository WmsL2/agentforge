"""Opt-in HTTP-to-Redis-to-Celery-to-PostgreSQL async run proof."""

import asyncio
import os
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_tool_registry
from app.core.config import settings
from app.core.security import create_access_token
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun
from app.db.models.workflow import WorkflowCheckpoint as DBCheckpoint
from app.db.models.workspace import Workspace
from app.main import app
from app.repositories import workspace as workspace_repo
from app.services.tool import ToolRegistry
from app.services.workflow import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    serialize_workflow_graph,
)
from app.services.workspace.domain import WorkspaceRole
from app.worker.celery_app import celery_app

DATABASE = "agentforge_v09_atomic5_verify"
HEAD = "0042_add_workflow_recovery_dispatch_schedule"
BACKEND_ROOT = Path(__file__).parents[3]


def definition() -> WorkflowDefinition:
    nodes = (
        WorkflowNode("start", WorkflowNodeKind.START),
        WorkflowNode("value", WorkflowNodeKind.VALUE, config={"value": "atomic-5"}),
        WorkflowNode("end", WorkflowNodeKind.END),
    )
    return WorkflowDefinition(
        uuid4(),
        "Atomic 5 API E2E",
        "start",
        nodes=nodes,
        edges=tuple(
            WorkflowEdge(f"{source.id}-{target.id}", source.id, target.id)
            for source, target in pairwise(nodes)
        ),
    )


def ping_redis() -> None:
    client = Redis.from_url(
        settings.CELERY_BROKER_URL,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        client.ping()
    finally:
        client.close()


async def wait_for_worker(hostname: str, worker: subprocess.Popen) -> list[str]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            output = worker.stdout.read() if worker.stdout is not None else ""
            pytest.fail(f"Celery worker exited during startup:\n{output}")
        replies = await asyncio.to_thread(
            celery_app.control.inspect(destination=[hostname], timeout=1).registered
        )
        if replies and hostname in replies:
            return replies[hostname]
        await asyncio.sleep(0.25)
    pytest.fail("Celery worker did not become ready within 30 seconds.")


@pytest.mark.anyio
async def test_async_run_api_reaches_real_worker_and_persisted_get() -> None:
    if os.getenv("AGENTFORGE_RUN_ASYNC_API_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_ASYNC_API_E2E=1 to run the full async API proof.")
    if os.getenv("AGENTFORGE_RUN_POSTGRES_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_POSTGRES_E2E=1 for the PostgreSQL-backed proof.")
    if settings.POSTGRES_DB != DATABASE:
        pytest.skip(f"Async API E2E requires POSTGRES_DB={DATABASE}.")

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    worker = None
    workspace_id = uuid4()
    user_id = uuid4()
    data_created = False
    previous_queue = celery_app.conf.task_default_queue
    try:
        try:
            async with engine.connect() as connection:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            await asyncio.to_thread(ping_redis)
        except (OSError, RedisError, SQLAlchemyError) as error:
            pytest.skip(f"PostgreSQL or Redis is unavailable ({type(error).__name__}).")
        if revision != HEAD:
            pytest.skip(f"Dedicated PostgreSQL must be at {HEAD}; found {revision!r}.")

        graph = definition()
        async with factory() as db:
            db.add(
                User(
                    id=user_id,
                    email=f"atomic5-api-{user_id.hex}@example.invalid",
                    hashed_password=None,
                )
            )
            await db.flush()
            workspace = await workspace_repo.create_workspace(
                db,
                workspace_id=workspace_id,
                name="Atomic 5 API E2E",
                created_by_user_id=user_id,
            )
            await workspace_repo.create_membership(
                db,
                workspace_id=workspace.id,
                user_id=user_id,
                role=WorkspaceRole.OWNER,
            )
            db.add(
                Workflow(
                    id=graph.id,
                    user_id=user_id,
                    workspace_id=workspace.id,
                    name=graph.name,
                    definition=serialize_workflow_graph(graph),
                    revision=1,
                )
            )
            await db.commit()
        data_created = True

        queue = f"agentforge-atomic5-{uuid4().hex}"
        hostname = f"atomic5-{uuid4().hex}@localhost"
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
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        registered = await wait_for_worker(hostname, worker)
        assert "agentforge.workflow.execute" in registered

        token = create_access_token(user_id)
        headers = {"Authorization": f"Bearer {token}"}
        app.dependency_overrides[get_tool_registry] = ToolRegistry
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            synchronous = await client.post(
                f"/api/v1/workflows/{graph.id}/runs",
                json={"input": {"mode": "sync"}},
                headers=headers,
            )
            assert synchronous.status_code == 201

            submitted = await client.post(
                f"/api/v1/workflows/{graph.id}/runs/async",
                json={"input": {"source": "http-e2e"}},
                headers=headers,
            )
            assert submitted.status_code == 202
            assert submitted.json()["status"] == "pending"
            run_id = UUID(submitted.json()["id"])
            assert submitted.headers["location"] == (f"/api/v1/workflows/{graph.id}/runs/{run_id}")

            deadline = time.monotonic() + 30
            while True:
                fetched = await client.get(
                    f"/api/v1/workflows/{graph.id}/runs/{run_id}", headers=headers
                )
                assert fetched.status_code == 200
                if fetched.json()["status"] == "completed":
                    break
                if time.monotonic() >= deadline:
                    pytest.fail(f"Run did not complete: {fetched.json()}")
                await asyncio.sleep(0.1)

        assert fetched.json()["output"] == {"end": {"value": "atomic-5"}}
        async with factory() as db:
            stored = await db.get(WorkflowRun, run_id)
            assert stored is not None
            assert stored.status == "completed"
            assert stored.input == {"source": "http-e2e"}
            assert stored.execution_claim_generation == 1
            assert stored.execution_claim_token is None
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(DBCheckpoint)
                    .where(DBCheckpoint.run_id == stored.id)
                )
                == 3
            )
    finally:
        app.dependency_overrides.clear()
        celery_app.conf.task_default_queue = previous_queue
        if worker is not None:
            worker.terminate()
            try:
                await asyncio.to_thread(worker.wait, 10)
            except subprocess.TimeoutExpired:
                worker.kill()
                await asyncio.to_thread(worker.wait, 5)
        if data_created:
            async with factory() as db:
                await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()
        await engine.dispose()
