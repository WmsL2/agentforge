"""Opt-in upload-to-Agent lifecycle over PostgreSQL, Redis and real Celery workers."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis import Redis
from sqlalchemy import delete, func, select

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.models.knowledge import KnowledgeDocument, KnowledgeDocumentChunk, KnowledgeIndexJob
from app.db.models.user import User
from app.db.models.workflow import WorkflowRun
from app.db.models.workflow.approval.model import ApprovalRequest
from app.db.models.workflow.checkpoint.model import WorkflowCheckpoint
from app.db.models.workflow.observability.run_step import WorkflowRunStep
from app.db.models.workflow.observability.trace_event import WorkflowTraceEvent
from app.db.models.workspace import Workspace
from app.main import app
from app.repositories import knowledge as knowledge_repo
from app.repositories import workspace as workspace_repo
from app.services.workspace import WorkspaceRole
from app.worker.celery_app import celery_app

DATABASE = "agentforge_v011_atomic8_verify"
BROKER_DB = "/15"
BACKEND_ROOT = Path(__file__).resolve().parents[3]
CONTENT = "Grass carp growth is related to body length and body weight."


class _ProviderHandler(BaseHTTPRequestHandler):
    """Deterministic OpenAI-compatible responses, only for this test process."""

    fail_embeddings = False

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        if self.path == "/v1/embeddings":
            if self.fail_embeddings:
                self.send_error(503, "test-only embedding outage")
                return
            assert payload["model"] == settings.EMBEDDING_MODEL
            assert payload["dimensions"] == 1536
            inputs = payload["input"]
            if isinstance(inputs, str):
                inputs = [inputs]
            response = {
                "object": "list",
                "model": settings.EMBEDDING_MODEL,
                "data": [
                    {"object": "embedding", "index": i, "embedding": [1.0] + [0.0] * 1535}
                    for i, _ in enumerate(inputs)
                ],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }
        elif self.path == "/v1/chat/completions":
            messages = payload["messages"]
            names = {tool["function"]["name"] for tool in payload.get("tools", [])}
            searched = any(message.get("role") == "tool" for message in messages)
            if "knowledge_search" in names and not searched:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{uuid4().hex}",
                            "type": "function",
                            "function": {
                                "name": "knowledge_search",
                                "arguments": json.dumps({"query": "grass carp growth", "top_k": 5}),
                            },
                        }
                    ],
                }
                finish_reason = "tool_calls"
            else:
                message = {"role": "assistant", "content": "Grounded grass carp answer."}
                finish_reason = "stop"
            response = {
                "id": f"chatcmpl-{uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": payload["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        else:
            self.send_error(404)
            return
        data = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return None


def _graph(base_id: UUID, *, agentic: bool, approval: bool = False) -> dict[str, object]:
    nodes = [{"id": "start", "kind": "start"}]
    if approval:
        nodes.append({"id": "approval", "kind": "approval", "config": {"prompt": "Continue?"}})
    if not agentic:
        nodes.append(
            {
                "id": "knowledge",
                "kind": "knowledge",
                "config": {
                    "knowledge_base_id": str(base_id),
                    "query_source": "workflow_input",
                    "input_key": "question",
                    "top_k": 5,
                },
            }
        )
    agent_config = {"runner": "langgraph", "instruction": "Answer using retrieved evidence."}
    if agentic:
        agent_config["knowledge_base_id"] = str(base_id)
    nodes.extend(
        [{"id": "agent", "kind": "agent", "config": agent_config}, {"id": "end", "kind": "end"}]
    )
    edges = [
        {"id": f"{a['id']}-{b['id']}", "source": a["id"], "target": b["id"]}
        for a, b in pairwise(nodes)
    ]
    return {"entry_node_id": "start", "nodes": nodes, "edges": edges}


async def _wait_for_worker(name: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"Celery worker exited during startup (code {process.returncode}).")
        registered = await asyncio.to_thread(
            celery_app.control.inspect(destination=[name], timeout=1).registered
        )
        if registered and name in registered:
            assert "agentforge.knowledge.index.execute" in registered[name]
            assert "agentforge.workflow.execute" in registered[name]
            assert "agentforge.knowledge.index.recovery.scan" in registered[name]
            assert "agentforge.workflow.recovery.scan" in registered[name]
            return
        await asyncio.sleep(0.25)
    pytest.fail("Atomic 8 Celery worker did not become ready within 30 seconds.")


async def _wait_for_db(factory, lookup, expected: str, *, timeout: float = 45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with factory() as db:
            row = await lookup(db)
            if row is not None and row.status == expected:
                return row
            if row is not None and row.status == "failed":
                detail = getattr(row, "error", getattr(row, "error_code", None))
                if isinstance(row, WorkflowRun):
                    events = (
                        await db.scalars(
                            select(WorkflowTraceEvent).where(WorkflowTraceEvent.run_id == row.id)
                        )
                    ).all()
                    detail = {
                        "run_error": detail,
                        "events": [
                            (event.kind, event.payload)
                            for event in events
                            if event.kind in {"agent_failed", "tool_failed"}
                        ],
                    }
                pytest.fail(f"Background execution failed: {detail}")
        await asyncio.sleep(0.25)
    pytest.fail(f"Background state did not reach {expected} within {timeout}s.")


@pytest.fixture
async def atomic8_runtime(postgres_restart_session_factory, tmp_path: Path, monkeypatch):
    if os.getenv("AGENTFORGE_RUN_ATOMIC8_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_ATOMIC8_E2E=1 for the real lifecycle proof.")
    if settings.POSTGRES_DB != DATABASE or not settings.CELERY_BROKER_URL.endswith(BROKER_DB):
        pytest.fail("Atomic 8 requires its isolated PostgreSQL database and Redis DB 15.")
    broker = Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2)
    try:
        assert await asyncio.to_thread(broker.ping)
    finally:
        broker.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    provider_url = f"http://127.0.0.1:{server.server_port}/v1"
    overrides = {
        "EMBEDDING_API_KEY": ("atomic8-test-only", "atomic8-test-only"),
        "EMBEDDING_BASE_URL": (provider_url, provider_url),
        "LLM_API_KEY": ("atomic8-test-only", "atomic8-test-only"),
        "LLM_BASE_URL": (provider_url, provider_url),
        "MEDIA_DIR": (str(tmp_path), tmp_path),
        "KNOWLEDGE_AGENT_ENABLED": ("true", True),
    }
    previous_settings = {key: getattr(settings, key) for key in overrides}
    previous_env = {key: os.environ.get(key) for key in overrides}
    queue = f"agentforge-atomic8-{uuid4().hex}"
    hostname = f"atomic8-{uuid4().hex}@localhost"
    previous_queue = celery_app.conf.task_default_queue
    try:
        with monkeypatch.context() as runtime_patch:
            for key, (env_value, setting_value) in overrides.items():
                runtime_patch.setenv(key, env_value)
                runtime_patch.setattr(settings, key, setting_value)
            worker_env = os.environ.copy()
            assert worker_env["EMBEDDING_BASE_URL"] == provider_url
            assert worker_env["LLM_BASE_URL"] == provider_url
            celery_app.conf.task_default_queue = queue
            worker: subprocess.Popen | None = None
            try:
                worker = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "celery",
                        "-A",
                        "app.worker.celery_app:celery_app",
                        "worker",
                        "--pool=solo",
                        "--concurrency=1",
                        "--loglevel=WARNING",
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
                    stderr=subprocess.STDOUT,
                    env=worker_env,
                )
                await _wait_for_worker(hostname, worker)
                yield postgres_restart_session_factory
            finally:
                try:
                    if worker is not None:
                        worker.terminate()
                        try:
                            await asyncio.to_thread(worker.wait, 10)
                        except subprocess.TimeoutExpired:
                            worker.kill()
                            await asyncio.to_thread(worker.wait, 5)
                        assert worker.poll() is not None
                finally:
                    celery_app.conf.task_default_queue = previous_queue
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
    assert all(getattr(settings, key) == value for key, value in previous_settings.items())
    assert all(os.environ.get(key) == value for key, value in previous_env.items())
    assert celery_app.conf.task_default_queue == previous_queue


@pytest.mark.anyio
async def test_upload_index_retrieve_agent_and_both_workflow_modes(
    atomic8_runtime, tmp_path: Path
) -> None:
    factory = atomic8_runtime
    owner_id, approver_id, workspace_id, foreign_id = uuid4(), uuid4(), uuid4(), uuid4()
    actor = {"id": owner_id}
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=actor["id"])
    try:
        async with factory() as db, db.begin():
            db.add(User(id=owner_id, email=f"atomic8-{owner_id.hex}@example.invalid"))
            db.add(User(id=approver_id, email=f"atomic8-{approver_id.hex}@example.invalid"))
            db.add(Workspace(id=workspace_id, name="Atomic 8 lifecycle"))
            db.add(Workspace(id=foreign_id, name="Atomic 8 foreign"))
            await db.flush()
            await workspace_repo.create_membership(
                db, workspace_id=workspace_id, user_id=owner_id, role=WorkspaceRole.OWNER
            )
            await workspace_repo.create_membership(
                db, workspace_id=workspace_id, user_id=approver_id, role=WorkspaceRole.ADMIN
            )
            foreign = await knowledge_repo.create(
                db,
                workspace_id=foreign_id,
                name="Hidden",
                description=None,
                created_by_user_id=None,
            )
            foreign_base_id = foreign.id
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            base_root = f"/api/v1/workspaces/{workspace_id}/knowledge-bases"
            created = await client.post(base_root, json={"name": "Lifecycle", "description": None})
            assert created.status_code == 201, created.text
            base_id = UUID(created.json()["id"])
            assert (await client.get(f"{base_root}/{foreign_base_id}")).status_code == 404
            document_root = f"{base_root}/{base_id}/documents"
            upload = await client.post(
                document_root, files={"file": ("growth.txt", CONTENT.encode(), "text/plain")}
            )
            assert upload.status_code == 201, upload.text
            document_id = UUID(upload.json()["id"])
            assert upload.json()["parse_status"] == "ready"
            assert "storage_path" not in upload.json()
            parsed = await client.get(f"{document_root}/{document_id}/content")
            assert parsed.status_code == 200 and parsed.json()["content"] == CONTENT
            search_root = f"{base_root}/{base_id}/search"
            before = await client.post(search_root, json={"query": "grass carp", "top_k": 1})
            assert before.status_code == 200 and before.json()["results"] == []

            submitted = await client.post(f"{document_root}/{document_id}/index")
            assert submitted.status_code == 202, submitted.text
            job_id = UUID(submitted.json()["id"])
            job = await _wait_for_db(
                factory, lambda db: db.get(KnowledgeIndexJob, job_id), "succeeded"
            )
            assert job.document_id == document_id and job.chunk_count >= 1
            async with factory() as db:
                document = await db.get(KnowledgeDocument, document_id)
                assert document is not None
                assert document.active_index_generation_id == job.index_generation_id
                chunks = (
                    await db.scalars(
                        select(KnowledgeDocumentChunk).where(
                            KnowledgeDocumentChunk.document_id == document_id,
                            KnowledgeDocumentChunk.index_generation_id == job.index_generation_id,
                        )
                    )
                ).all()
                assert len(chunks) == job.chunk_count
                assert all(
                    chunk.content == CONTENT[chunk.start_offset : chunk.end_offset]
                    for chunk in chunks
                )
                chunk_id = chunks[0].id
            duplicate = celery_app.send_task(
                "agentforge.knowledge.index.execute", args=[str(job_id)]
            )
            assert (await asyncio.to_thread(duplicate.get, timeout=30))["status"] == "not_claimed"
            with suppress(Exception):
                duplicate.forget()
            found = await client.post(search_root, json={"query": "grass carp", "top_k": 1})
            assert found.status_code == 200, found.text
            result = found.json()["results"][0]
            assert result["chunk_id"] == str(chunk_id)
            assert result["document_id"] == str(document_id)
            assert result["filename"] == "growth.txt"
            assert result["content"] == CONTENT[result["start_offset"] : result["end_offset"]]
            assert "embedding" not in result and "storage_path" not in result
            ask = await client.post(
                f"{base_root}/{base_id}/ask", json={"question": "grass carp growth?"}
            )
            assert ask.status_code == 200, ask.text
            assert ask.json()["status"] == "answered"
            assert ask.json()["sources"][0]["chunk_id"] == str(chunk_id)

            for agentic in (False, True):
                workflow = await client.post(
                    f"/api/v1/workflows?workspace_id={workspace_id}",
                    json={
                        "name": f"Atomic 8 {'agentic' if agentic else 'explicit'}",
                        "definition": _graph(base_id, agentic=agentic),
                    },
                )
                assert workflow.status_code == 201, workflow.text
                workflow_id = UUID(workflow.json()["id"])
                run = await client.post(
                    f"/api/v1/workflows/{workflow_id}/runs/async",
                    json={"input": {"question": "grass carp growth"}},
                )
                assert run.status_code == 202, run.text
                run_id = UUID(run.json()["id"])
                completed = await _wait_for_db(
                    factory,
                    lambda db, current_run_id=run_id: db.get(WorkflowRun, current_run_id),
                    "completed",
                )
                assert completed.actor_user_id == owner_id
                async with factory() as db:
                    steps = (
                        await db.scalars(
                            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)
                        )
                    ).all()
                    checkpoints = await db.scalar(
                        select(func.count())
                        .select_from(WorkflowCheckpoint)
                        .where(WorkflowCheckpoint.run_id == run_id)
                    )
                    assert checkpoints == len(steps) >= (3 if agentic else 4)
                    if agentic:
                        assert completed.node_outputs["agent"]["status"] == "answered"
                        assert completed.node_outputs["agent"]["sources"][0]["chunk_id"] == str(
                            chunk_id
                        )
                        traces = (
                            await db.scalars(
                                select(WorkflowTraceEvent).where(
                                    WorkflowTraceEvent.run_id == run_id
                                )
                            )
                        ).all()
                        assert any(
                            event.kind == "tool_completed" and event.step_id for event in traces
                        )
                    else:
                        assert completed.node_outputs["knowledge"]["results"][0]["chunk_id"] == str(
                            chunk_id
                        )
                replay = celery_app.send_task(
                    "agentforge.workflow.execute", kwargs={"run_id": str(run_id)}
                )
                assert (await asyncio.to_thread(replay.get, timeout=30))["status"] == "not_claimed"
                with suppress(Exception):
                    replay.forget()

            approval_flow = await client.post(
                f"/api/v1/workflows?workspace_id={workspace_id}",
                json={
                    "name": "Atomic 8 approval",
                    "definition": _graph(base_id, agentic=True, approval=True),
                },
            )
            assert approval_flow.status_code == 201, approval_flow.text
            approval_workflow_id = UUID(approval_flow.json()["id"])
            pending_run = await client.post(
                f"/api/v1/workflows/{approval_workflow_id}/runs/async",
                json={"input": {"question": "grass carp growth"}},
            )
            assert pending_run.status_code == 202, pending_run.text
            approval_run_id = UUID(pending_run.json()["id"])
            await _wait_for_db(factory, lambda db: db.get(WorkflowRun, approval_run_id), "paused")
            async with factory() as db:
                approval = await db.scalar(
                    select(ApprovalRequest).where(ApprovalRequest.run_id == approval_run_id)
                )
                assert approval is not None
                approval_id = approval.id
            actor["id"] = approver_id
            approved = await client.post(
                f"/api/v1/workflows/{approval_workflow_id}/runs/{approval_run_id}/approvals/{approval_id}/approve/async",
                json={"note": "approved by another member"},
            )
            assert approved.status_code == 202, approved.text
            actor["id"] = owner_id
            resumed = await _wait_for_db(
                factory, lambda db: db.get(WorkflowRun, approval_run_id), "completed"
            )
            assert resumed.actor_user_id == owner_id
            assert resumed.node_outputs["agent"]["sources"][0]["chunk_id"] == str(chunk_id)

            _ProviderHandler.fail_embeddings = True
            try:
                failed_request = await client.post(f"{document_root}/{document_id}/index")
                assert failed_request.status_code == 202
                failed_id = UUID(failed_request.json()["id"])
                failed_job = await _wait_for_db(
                    factory, lambda db: db.get(KnowledgeIndexJob, failed_id), "failed"
                )
                assert failed_job.error_code is not None
                async with factory() as db:
                    persisted = await db.get(KnowledgeDocument, document_id)
                    assert persisted.active_index_generation_id == job.index_generation_id
            finally:
                _ProviderHandler.fail_embeddings = False
            reindex = await client.post(f"{document_root}/{document_id}/index")
            assert reindex.status_code == 202
            new_id = UUID(reindex.json()["id"])
            assert new_id != job_id
            new_job = await _wait_for_db(
                factory, lambda db: db.get(KnowledgeIndexJob, new_id), "succeeded"
            )
            assert new_job.index_generation_id != job.index_generation_id
            async with factory() as db:
                persisted = await db.get(KnowledgeDocument, document_id)
                assert persisted.active_index_generation_id == new_job.index_generation_id

            removed = await client.delete(f"{document_root}/{document_id}")
            assert removed.status_code == 204
            assert not list((tmp_path / "knowledge").rglob("*.txt"))
            after = await client.post(search_root, json={"query": "grass carp", "top_k": 1})
            assert after.status_code == 200 and after.json()["results"] == []

            for task_name in (
                "agentforge.knowledge.index.recovery.scan",
                "agentforge.workflow.recovery.scan",
            ):
                scan = celery_app.send_task(task_name)
                outcome = await asyncio.to_thread(scan.get, timeout=30)
                assert outcome["failed"] == 0 and outcome["dispatched"] == 0
                with suppress(Exception):
                    scan.forget()
    finally:
        app.dependency_overrides.clear()
        async with factory() as db, db.begin():
            await db.execute(delete(Workspace).where(Workspace.id.in_([workspace_id, foreign_id])))
            await db.execute(delete(User).where(User.id == owner_id))
            await db.execute(delete(User).where(User.id == approver_id))
