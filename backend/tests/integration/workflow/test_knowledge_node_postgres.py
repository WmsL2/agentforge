"""PostgreSQL + pgvector proofs for the trusted Workflow KNOWLEDGE node."""

import hashlib
import os
from datetime import timedelta
from itertools import pairwise
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, update

from app.db.models.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeIndexJob,
)
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowRun
from app.db.models.workspace import Workspace, WorkspaceMembership
from app.repositories import knowledge as knowledge_repo
from app.repositories import workspace as workspace_repo
from app.services.agent_runtime import AgentExecutionResult
from app.services.knowledge.retrieval_service import KnowledgeRetrievalService
from app.services.workflow import (
    AgentNodeExecutor,
    ApprovalNodeExecutor,
    BackgroundRunExecutionStatus,
    BackgroundRunExecutor,
    DeterministicNodeExecutor,
    DispatchingNodeExecutor,
    KnowledgeNodeExecutor,
    WorkflowApprovalService,
    WorkflowAsyncRunService,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowExecutionJob,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowService,
    serialize_workflow_graph,
)
from app.services.workspace import WorkspaceRole
from app.services.workspace.authorization import WorkspaceAuthorizationService

DATABASE = "agentforge_v011_atomic6_verify"
MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
LEASE = timedelta(minutes=2)


class DeterministicEmbeddingProvider:
    model = MODEL
    dimensions = DIMENSIONS

    def __init__(self, calls: list[list[str]]) -> None:
        self._calls = calls

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._calls.append(texts)
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]


class DeterministicAgentRunner:
    def __init__(self) -> None:
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return AgentExecutionResult(output={"grounded_input": request.input})


class SimulatedProcessCrash(BaseException):
    """Test-only crash that bypasses normal node failure persistence."""


class CrashingAgentRunner:
    async def run(self, request):
        raise SimulatedProcessCrash


class RecordingDispatcher:
    def __init__(self) -> None:
        self.jobs = []

    async def dispatch(self, job) -> None:
        self.jobs.append(job)


def definition(knowledge_base_id: UUID, *, approval: bool = False) -> WorkflowDefinition:
    nodes = [WorkflowNode("start", WorkflowNodeKind.START)]
    if approval:
        nodes.append(
            WorkflowNode("approval", WorkflowNodeKind.APPROVAL, {"prompt": "Continue retrieval?"})
        )
    nodes.extend(
        [
            WorkflowNode(
                "knowledge",
                WorkflowNodeKind.KNOWLEDGE,
                {
                    "knowledge_base_id": str(knowledge_base_id),
                    "query_source": "workflow_input",
                    "input_key": "question",
                    "top_k": 5,
                },
            ),
            WorkflowNode(
                "agent",
                WorkflowNodeKind.AGENT,
                {"runner": "langgraph", "instruction": "Answer only from retrieved evidence."},
            ),
            WorkflowNode("end", WorkflowNodeKind.END),
        ]
    )
    return WorkflowDefinition(
        id=uuid4(),
        name="Atomic 6 knowledge workflow",
        entry_node_id="start",
        nodes=tuple(nodes),
        edges=tuple(
            WorkflowEdge(f"{source.id}-{target.id}", source.id, target.id)
            for source, target in pairwise(nodes)
        ),
    )


def engine(
    factory, embedding_calls, runner=None
) -> tuple[WorkflowEngine, DeterministicAgentRunner]:
    agent_runner = runner or DeterministicAgentRunner()
    retrieval = KnowledgeRetrievalService(
        cast(Any, factory),
        lambda: DeterministicEmbeddingProvider(embedding_calls),
        embedding_model=MODEL,
        embedding_dimensions=DIMENSIONS,
        embedding_timeout_seconds=2,
        db_statement_timeout_ms=5000,
    )
    dispatch = DispatchingNodeExecutor(
        DeterministicNodeExecutor(),
        AgentNodeExecutor({"langgraph": agent_runner}),
        ApprovalNodeExecutor(),
        knowledge_executor=KnowledgeNodeExecutor(retrieval),
    )
    return WorkflowEngine(dispatch), agent_runner


async def create_scope(factory, *, approval: bool = False):
    actor_id, workspace_id = uuid4(), uuid4()
    document_id, generation_id, chunk_id = uuid4(), uuid4(), uuid4()
    content = "草鱼体重与体长存在相关关系。"
    async with factory() as db, db.begin():
        db.add(User(id=actor_id, email=f"atomic6-{actor_id.hex}@example.invalid"))
        db.add(Workspace(id=workspace_id, name="Atomic 6 proof"))
        await db.flush()
        await workspace_repo.create_membership(
            db, workspace_id=workspace_id, user_id=actor_id, role=WorkspaceRole.OWNER
        )
        knowledge_base = await knowledge_repo.create(
            db,
            workspace_id=workspace_id,
            name="Atomic 6 knowledge",
            description=None,
            created_by_user_id=actor_id,
        )
        knowledge_base_id = knowledge_base.id
        graph = definition(knowledge_base_id, approval=approval)
        snapshot = serialize_workflow_graph(graph)
        db.add(
            Workflow(
                id=graph.id,
                user_id=actor_id,
                workspace_id=workspace_id,
                name=graph.name,
                definition=snapshot,
                revision=1,
            )
        )
        db.add(
            KnowledgeDocument(
                id=document_id,
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base_id,
                created_by_user_id=actor_id,
                filename="fish.pdf",
                mime_type="application/pdf",
                size_bytes=len(content.encode()),
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                storage_path=f"{workspace_id}/{knowledge_base_id}/{document_id}/fish.pdf",
                parse_status="ready",
                parsed_content=content,
                page_count=1,
                parse_metadata={},
                active_index_generation_id=generation_id,
            )
        )
        await db.flush()
        db.add(
            KnowledgeIndexJob(
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
                index_generation_id=generation_id,
                status="succeeded",
                embedding_model=MODEL,
                embedding_dimensions=DIMENSIONS,
                chunking_config_version="character-v1:1000:150:2500",
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                attempt_count=1,
                claim_generation=1,
                chunk_count=1,
            )
        )
        db.add(
            KnowledgeDocumentChunk(
                id=chunk_id,
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
                index_generation_id=generation_id,
                chunk_index=0,
                content=content,
                start_offset=0,
                end_offset=len(content),
                page_start=2,
                page_end=2,
                chunk_metadata={},
                embedding_model=MODEL,
                embedding=[1.0] + [0.0] * (DIMENSIONS - 1),
            )
        )
    return SimpleNamespace(
        actor_id=actor_id,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        workflow_id=graph.id,
        chunk_id=chunk_id,
        snapshot=snapshot,
    )


async def cleanup(factory, scope) -> None:
    async with factory() as db, db.begin():
        await db.execute(delete(Workspace).where(Workspace.id == scope.workspace_id))
        await db.execute(delete(User).where(User.id == scope.actor_id))


@pytest.fixture
def atomic6_factory(postgres_restart_session_factory):
    if os.getenv("AGENTFORGE_RUN_ATOMIC6_KNOWLEDGE_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_ATOMIC6_KNOWLEDGE_E2E=1 for Atomic 6 proofs.")
    from app.core.config import settings

    if settings.POSTGRES_DB != DATABASE:
        pytest.skip(f"Atomic 6 proof requires POSTGRES_DB={DATABASE}.")
    return postgres_restart_session_factory


@pytest.mark.anyio
async def test_async_worker_persists_identity_sources_and_does_not_replay_checkpoint(
    atomic6_factory,
) -> None:
    factory = atomic6_factory
    scope = await create_scope(factory)
    embedding_calls: list[list[str]] = []
    workflow_engine, agent_runner = engine(factory, embedding_calls)
    dispatcher = RecordingDispatcher()
    try:
        async with factory() as db:
            service = WorkflowAsyncRunService(
                db,
                WorkflowService(db, WorkspaceAuthorizationService(db)),
                dispatcher,
            )
            created = await service.submit_workflow(
                scope.workflow_id, scope.actor_id, {"question": "草鱼关系"}
            )
            assert created.actor_user_id == scope.actor_id
        job = dispatcher.jobs[0]
        result = await BackgroundRunExecutor(
            factory, workflow_engine, lease_duration=LEASE
        ).execute(job)
        assert result.status is BackgroundRunExecutionStatus.COMPLETED
        async with factory() as db:
            stored = await db.get(WorkflowRun, job.run_id)
            assert stored is not None and stored.actor_user_id == scope.actor_id
            output = stored.node_outputs["knowledge"]
            assert output["results"][0]["chunk_id"] == str(scope.chunk_id)
            assert output["results"][0]["filename"] == "fish.pdf"
        duplicate = await BackgroundRunExecutor(
            factory, workflow_engine, lease_duration=LEASE
        ).execute(job)
        assert duplicate.status is BackgroundRunExecutionStatus.NOT_CLAIMED
        assert embedding_calls == [["草鱼关系"]]
        assert len(agent_runner.requests) == 1
    finally:
        await cleanup(factory, scope)


@pytest.mark.anyio
async def test_membership_revocation_cross_workspace_and_historical_identity_fail_closed(
    atomic6_factory,
) -> None:
    factory = atomic6_factory
    scope = await create_scope(factory)
    embedding_calls: list[list[str]] = []
    workflow_engine, _ = engine(factory, embedding_calls)
    try:
        run_ids = []
        for actor_user_id in (scope.actor_id, None):
            run_id = uuid4()
            run_ids.append(run_id)
            async with factory() as db, db.begin():
                db.add(
                    WorkflowRun(
                        id=run_id,
                        workflow_id=scope.workflow_id,
                        workflow_revision=1,
                        actor_user_id=actor_user_id,
                        definition_snapshot=scope.snapshot,
                        status="pending",
                        input={"question": "must not leak"},
                    )
                )
        async with factory() as db, db.begin():
            await db.execute(
                delete(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == scope.workspace_id,
                    WorkspaceMembership.user_id == scope.actor_id,
                )
            )
        for run_id in run_ids:
            result = await BackgroundRunExecutor(
                factory, workflow_engine, lease_duration=LEASE
            ).execute(WorkflowExecutionJob(run_id))
            assert result.status is BackgroundRunExecutionStatus.FAILED
            async with factory() as db:
                stored = await db.get(WorkflowRun, run_id)
                assert stored is not None
                assert stored.error["message"] in {
                    "Knowledge retrieval failed.",
                    "Knowledge node requires trusted run identity.",
                }
        assert embedding_calls == []
    finally:
        await cleanup(factory, scope)


@pytest.mark.anyio
async def test_cross_workspace_knowledge_base_is_hidden(atomic6_factory) -> None:
    factory = atomic6_factory
    target = await create_scope(factory)
    foreign = await create_scope(factory)
    embedding_calls: list[list[str]] = []
    workflow_engine, _ = engine(factory, embedding_calls)
    dispatcher = RecordingDispatcher()
    try:
        cross_definition = definition(foreign.knowledge_base_id)
        cross_definition.id = target.workflow_id
        snapshot = serialize_workflow_graph(cross_definition)
        async with factory() as db, db.begin():
            workflow = await db.get(Workflow, target.workflow_id)
            assert workflow is not None
            workflow.definition = snapshot
        async with factory() as db:
            await WorkflowAsyncRunService(
                db,
                WorkflowService(db, WorkspaceAuthorizationService(db)),
                dispatcher,
            ).submit_workflow(target.workflow_id, target.actor_id, {"question": "hidden"})
        result = await BackgroundRunExecutor(
            factory, workflow_engine, lease_duration=LEASE
        ).execute(dispatcher.jobs[0])
        assert result.status is BackgroundRunExecutionStatus.FAILED
        async with factory() as db:
            stored = await db.get(WorkflowRun, dispatcher.jobs[0].run_id)
            assert stored is not None
            assert stored.error["message"] == "Knowledge retrieval failed."
        assert embedding_calls == []
    finally:
        await cleanup(factory, target)
        await cleanup(factory, foreign)


@pytest.mark.anyio
async def test_recovery_does_not_repeat_committed_knowledge_retrieval(atomic6_factory) -> None:
    factory = atomic6_factory
    scope = await create_scope(factory)
    embedding_calls: list[list[str]] = []
    crashing_engine, _ = engine(factory, embedding_calls, runner=CrashingAgentRunner())
    dispatcher = RecordingDispatcher()
    try:
        async with factory() as db:
            await WorkflowAsyncRunService(
                db,
                WorkflowService(db, WorkspaceAuthorizationService(db)),
                dispatcher,
            ).submit_workflow(scope.workflow_id, scope.actor_id, {"question": "recover once"})
        job = dispatcher.jobs[0]
        with pytest.raises(SimulatedProcessCrash):
            await BackgroundRunExecutor(factory, crashing_engine, lease_duration=LEASE).execute(job)
        assert embedding_calls == [["recover once"]]
        async with factory() as db, db.begin():
            await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == job.run_id)
                .values(execution_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
            )
        healthy_engine, healthy_runner = engine(factory, embedding_calls)
        recovered = await BackgroundRunExecutor(
            factory, healthy_engine, lease_duration=LEASE
        ).execute(job)
        assert recovered.status is BackgroundRunExecutionStatus.COMPLETED
        assert embedding_calls == [["recover once"]]
        assert len(healthy_runner.requests) == 1
    finally:
        await cleanup(factory, scope)


@pytest.mark.anyio
async def test_approval_resume_uses_original_submitter_identity(atomic6_factory) -> None:
    factory = atomic6_factory
    scope = await create_scope(factory, approval=True)
    embedding_calls: list[list[str]] = []
    workflow_engine, _ = engine(factory, embedding_calls)
    dispatcher = RecordingDispatcher()
    try:
        async with factory() as db:
            workflow_service = WorkflowService(db, WorkspaceAuthorizationService(db))
            created = await WorkflowAsyncRunService(
                db, workflow_service, dispatcher
            ).submit_workflow(scope.workflow_id, scope.actor_id, {"question": "approval query"})
        await BackgroundRunExecutor(factory, workflow_engine, lease_duration=LEASE).execute(
            dispatcher.jobs[0]
        )
        async with factory() as db:
            workflow_service = WorkflowService(db, WorkspaceAuthorizationService(db))
            approval_service = WorkflowApprovalService(
                db,
                workflow_service,
                workflow_engine,
                session_factory=factory,
                lease_duration=LEASE,
            )
            pending = await approval_service.get_pending_approval(
                scope.workflow_id, created.id, scope.actor_id
            )
            await approval_service.approve(
                scope.workflow_id, created.id, pending.id, scope.actor_id
            )
        async with factory() as db:
            stored = await db.get(WorkflowRun, created.id)
            assert stored is not None and stored.status == "completed"
            assert stored.actor_user_id == scope.actor_id
            assert stored.node_outputs["knowledge"]["query"] == "approval query"
        assert embedding_calls == [["approval query"]]
    finally:
        await cleanup(factory, scope)
