"""Opt-in real Redis, Celery worker, and PostgreSQL workflow-adapter proof."""

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from celery import Celery
from celery.result import AsyncResult
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.models.workflow import Workflow, WorkflowRun
from app.db.models.workflow import WorkflowCheckpoint as DBCheckpoint
from app.db.models.workflow.observability.run_step import WorkflowRunStep
from app.db.models.workspace import Workspace
from app.integrations.celery.workflow_dispatcher import CeleryWorkflowDispatcher
from app.services.workflow import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowExecutionJob,
    WorkflowNode,
    WorkflowNodeKind,
    serialize_workflow_graph,
)
from app.worker.celery_app import celery_app

DATABASE = "agentforge_v09_atomic4_verify"
HEAD = "0041_add_workflow_execution_claim_lease"
BACKEND_ROOT = Path(__file__).parents[3]


@dataclass
class RecordingPublisher:
    """Retain task handles for test assertions without changing the adapter contract."""

    app: Celery
    results: list[AsyncResult] = field(default_factory=list)

    def send_task(self, name: str, *, kwargs: dict[str, str]) -> AsyncResult:
        result = self.app.send_task(name, kwargs=kwargs)
        self.results.append(result)
        return result


def deterministic_definition() -> WorkflowDefinition:
    nodes = (
        WorkflowNode("start", WorkflowNodeKind.START),
        WorkflowNode("value", WorkflowNodeKind.VALUE, config={"value": "atomic-4"}),
        WorkflowNode("end", WorkflowNodeKind.END),
    )
    return WorkflowDefinition(
        uuid4(),
        "Atomic 4 Celery proof",
        "start",
        nodes=nodes,
        edges=tuple(
            WorkflowEdge(f"{source.id}-{target.id}", source.id, target.id)
            for source, target in pairwise(nodes)
        ),
    )


@pytest.fixture
async def celery_e2e() -> AsyncIterator[
    tuple[
        async_sessionmaker[AsyncSession],
        CeleryWorkflowDispatcher,
        RecordingPublisher,
        list[str],
    ]
]:
    if os.getenv("AGENTFORGE_RUN_CELERY_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_CELERY_E2E=1 to run the real Celery adapter proof.")
    if os.getenv("AGENTFORGE_RUN_POSTGRES_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_POSTGRES_E2E=1 for the PostgreSQL-backed proof.")
    if settings.POSTGRES_DB != DATABASE:
        pytest.skip(f"Celery adapter proof requires POSTGRES_DB={DATABASE}.")

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        try:
            async with engine.connect() as connection:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        except Exception as error:
            pytest.skip(f"Dedicated PostgreSQL is unavailable ({type(error).__name__}).")
        if revision != HEAD:
            pytest.skip(f"Dedicated PostgreSQL must be at {HEAD}; found {revision!r}.")
        try:
            await asyncio.to_thread(_ping_redis)
        except (OSError, RedisError) as error:
            pytest.skip(f"Redis broker is unavailable ({type(error).__name__}).")

        queue = f"agentforge-atomic4-{uuid4().hex}"
        hostname = f"atomic4-{uuid4().hex}@localhost"
        celery_app.conf.task_default_queue = queue
        publisher = RecordingPublisher(celery_app)
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
        try:
            registered = await _wait_for_worker(celery_app, hostname, worker)
            yield factory, CeleryWorkflowDispatcher(publisher), publisher, registered
        finally:
            worker.terminate()
            try:
                await asyncio.to_thread(worker.wait, 10)
            except subprocess.TimeoutExpired:
                worker.kill()
                await asyncio.to_thread(worker.wait, 5)
            for result in publisher.results:
                with suppress(Exception):
                    result.forget()
    finally:
        await engine.dispose()


def _ping_redis() -> None:
    client = Redis.from_url(
        settings.CELERY_BROKER_URL,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        client.ping()
    finally:
        client.close()


async def _wait_for_worker(app: Celery, hostname: str, worker: subprocess.Popen) -> list[str]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            output = worker.stdout.read() if worker.stdout is not None else ""
            pytest.fail(f"Celery worker exited during startup:\n{output}")
        replies = await asyncio.to_thread(
            app.control.inspect(destination=[hostname], timeout=1).registered
        )
        if replies and hostname in replies:
            return replies[hostname]
        await asyncio.sleep(0.25)
    pytest.fail("Celery worker did not become ready within 30 seconds.")


async def _create_run(
    factory: async_sessionmaker[AsyncSession], *, corrupt: bool = False
) -> tuple[UUID, UUID]:
    definition = deterministic_definition()
    workspace_id, run_id = uuid4(), uuid4()
    snapshot = {} if corrupt else serialize_workflow_graph(definition)
    async with factory() as db:
        db.add(Workspace(id=workspace_id, name="Atomic 4 proof"))
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
                definition_snapshot=snapshot,
                status="pending",
                input={"source": "celery-e2e"},
            )
        )
        await db.commit()
    return workspace_id, run_id


async def _result(result: AsyncResult, *, propagate: bool = True):
    return await asyncio.to_thread(result.get, timeout=30, propagate=propagate)


@pytest.mark.anyio
async def test_real_celery_worker_executes_fences_and_reports_failures(celery_e2e) -> None:
    factory, dispatcher, publisher, registered = celery_e2e
    workspace_ids = []
    try:
        assert "agentforge.smoke.echo" in registered
        assert "agentforge.workflow.execute" in registered

        workspace_id, run_id = await _create_run(factory)
        workspace_ids.append(workspace_id)
        await asyncio.gather(
            dispatcher.dispatch(WorkflowExecutionJob(run_id)),
            dispatcher.dispatch(WorkflowExecutionJob(run_id)),
        )
        outcomes = [await _result(result) for result in publisher.results[:2]]
        assert {outcome["status"] for outcome in outcomes} == {"completed", "not_claimed"}
        by_status = {outcome["status"]: outcome for outcome in outcomes}
        assert by_status["completed"]["lease_released"] is True
        assert by_status["not_claimed"]["lease_released"] is False

        async with factory() as db:
            run = await db.get(WorkflowRun, run_id)
            assert run is not None
            assert run.status == "completed"
            assert run.output == {"end": {"value": "atomic-4"}}
            assert run.execution_claim_generation == 1
            assert run.execution_claim_token is None
            assert run.execution_lease_expires_at is None
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(DBCheckpoint)
                    .where(DBCheckpoint.run_id == run_id)
                )
                == 3
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(WorkflowRunStep)
                    .where(WorkflowRunStep.run_id == run_id)
                )
                == 3
            )

        bad_workspace_id, bad_run_id = await _create_run(factory, corrupt=True)
        workspace_ids.append(bad_workspace_id)
        await dispatcher.dispatch(WorkflowExecutionJob(bad_run_id))
        failed_result = publisher.results[2]
        await _result(failed_result, propagate=False)
        assert failed_result.state == "FAILURE"
        async with factory() as db:
            bad_run = await db.get(WorkflowRun, bad_run_id)
            assert bad_run is not None
            assert bad_run.status == "pending"
            assert bad_run.execution_claim_token is not None
            assert bad_run.execution_lease_expires_at is not None
    finally:
        if workspace_ids:
            async with factory() as db:
                await db.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
                await db.commit()
