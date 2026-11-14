"""PostgreSQL and pgvector proof for Workflow AGENT LangGraph knowledge calls."""

import os
from datetime import timedelta
from itertools import pairwise
from typing import Any, cast
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import delete, func, update

from app.db.models.workflow import Workflow, WorkflowRun
from app.db.models.workspace import WorkspaceMembership
from app.services.agent_runtime.runner.implementations import LangGraphAgentRunner
from app.services.knowledge.retrieval_service import KnowledgeRetrievalService
from app.services.tool import ToolDefinition, ToolRegistry
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor
from app.services.workflow import (
    AgentNodeExecutor,
    ApprovalNodeExecutor,
    BackgroundRunExecutionStatus,
    BackgroundRunExecutor,
    DeterministicNodeExecutor,
    DispatchingNodeExecutor,
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
from app.services.workflow.execution.executor.agent.knowledge import (
    WorkflowAgentKnowledgeComposition,
)
from app.services.workspace.authorization import WorkspaceAuthorizationService
from tests.integration.workflow.test_knowledge_node_postgres import (
    DIMENSIONS,
    LEASE,
    MODEL,
    DeterministicAgentRunner,
    DeterministicEmbeddingProvider,
    RecordingDispatcher,
    SimulatedProcessCrash,
    cleanup,
    create_scope,
)

DATABASE = "agentforge_v011_atomic7_verify"


class ScriptedModel:
    def __init__(self, *, search: bool = True) -> None:
        self.search = search
        self.calls = 0
        self.tools = []

    def bind_tools(self, tools):
        self.tools = [tool.name for tool in tools]
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.search and self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_search",
                        "args": {"query": "草鱼关系", "top_k": 5},
                        "id": f"call-{uuid4().hex}",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="Grounded answer")


class CrashingModel(ScriptedModel):
    async def ainvoke(self, messages):
        raise SimulatedProcessCrash


def definition(base_id, *, approval=False):
    nodes = [WorkflowNode("start", WorkflowNodeKind.START)]
    if approval:
        nodes.append(WorkflowNode("approval", WorkflowNodeKind.APPROVAL, {"prompt": "Continue?"}))
    nodes.extend(
        [
            WorkflowNode(
                "agent",
                WorkflowNodeKind.AGENT,
                {
                    "runner": "langgraph",
                    "instruction": "Use knowledge_search before answering.",
                    "knowledge_base_id": str(base_id),
                },
            ),
            WorkflowNode("end", WorkflowNodeKind.END),
        ]
    )
    return WorkflowDefinition(
        id=uuid4(),
        name="Atomic 7 agent knowledge",
        entry_node_id="start",
        nodes=tuple(nodes),
        edges=tuple(WorkflowEdge(f"{a.id}-{b.id}", a.id, b.id) for a, b in pairwise(nodes)),
    )


async def configure_workflow(factory, scope, *, base_id=None, approval=False):
    graph = definition(base_id or scope.knowledge_base_id, approval=approval)
    graph.id = scope.workflow_id
    async with factory() as db, db.begin():
        workflow = await db.get(Workflow, scope.workflow_id)
        assert workflow is not None
        workflow.definition = serialize_workflow_graph(graph)
    return graph


def engine(factory, model, embedding_calls):
    retrieval = KnowledgeRetrievalService(
        cast(Any, factory),
        lambda: DeterministicEmbeddingProvider(embedding_calls),
        embedding_model=MODEL,
        embedding_dimensions=DIMENSIONS,
        embedding_timeout_seconds=2,
        db_statement_timeout_ms=5000,
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("current_datetime", "Clock", {"type": "object", "properties": {}}),
        NativeCallableToolExecutor(lambda: "now"),
    )
    composition = WorkflowAgentKnowledgeComposition(
        retrieval,
        registry,
        lambda tools, limit: LangGraphAgentRunner(
            model_factory=lambda _: model,
            tools=tools,
            recursion_limit=limit,
        ),
        timeout_seconds=5,
        maximum_calls=2,
    )
    dispatch = DispatchingNodeExecutor(
        DeterministicNodeExecutor(),
        AgentNodeExecutor({"langgraph": DeterministicAgentRunner()}, knowledge=composition),
        ApprovalNodeExecutor(),
    )
    return WorkflowEngine(dispatch)


async def submit(factory, scope, dispatcher):
    async with factory() as db:
        return await WorkflowAsyncRunService(
            db,
            WorkflowService(db, WorkspaceAuthorizationService(db)),
            dispatcher,
        ).submit_workflow(scope.workflow_id, scope.actor_id, {"question": "草鱼关系"})


@pytest.fixture
def atomic7_factory(postgres_restart_session_factory):
    if os.getenv("AGENTFORGE_RUN_ATOMIC7_KNOWLEDGE_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_ATOMIC7_KNOWLEDGE_E2E=1 for Atomic 7 proofs.")
    from app.core.config import settings

    if settings.POSTGRES_DB != DATABASE:
        pytest.skip(f"Atomic 7 proof requires POSTGRES_DB={DATABASE}.")
    return postgres_restart_session_factory


@pytest.mark.anyio
async def test_langgraph_toolnode_pgvector_sources_checkpoint_and_replay(atomic7_factory):
    factory = atomic7_factory
    scope = await create_scope(factory)
    model = ScriptedModel()
    embeddings = []
    dispatcher = RecordingDispatcher()
    try:
        await configure_workflow(factory, scope)
        await submit(factory, scope, dispatcher)
        job = dispatcher.jobs[0]
        result = await BackgroundRunExecutor(
            factory, engine(factory, model, embeddings), lease_duration=LEASE
        ).execute(job)
        assert result.status is BackgroundRunExecutionStatus.COMPLETED
        async with factory() as db:
            stored = await db.get(WorkflowRun, job.run_id)
            assert stored is not None
            output = stored.node_outputs["agent"]
            assert output["status"] == "answered"
            assert output["answer"] == "Grounded answer"
            assert output["sources"][0]["chunk_id"] == str(scope.chunk_id)
            assert output["sources"][0]["filename"] == "fish.pdf"
        assert set(model.tools) == {"current_datetime", "knowledge_search"}
        assert embeddings == [["草鱼关系"]]
        replay = await BackgroundRunExecutor(
            factory, engine(factory, model, embeddings), lease_duration=LEASE
        ).execute(job)
        assert replay.status is BackgroundRunExecutionStatus.NOT_CLAIMED
        assert model.calls == 2
    finally:
        await cleanup(factory, scope)


@pytest.mark.anyio
async def test_revoked_member_is_denied_before_model_call(atomic7_factory):
    factory = atomic7_factory
    scope = await create_scope(factory)
    model = ScriptedModel()
    dispatcher = RecordingDispatcher()
    try:
        await configure_workflow(factory, scope)
        await submit(factory, scope, dispatcher)
        async with factory() as db, db.begin():
            await db.execute(
                delete(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == scope.workspace_id,
                    WorkspaceMembership.user_id == scope.actor_id,
                )
            )
        result = await BackgroundRunExecutor(
            factory, engine(factory, model, []), lease_duration=LEASE
        ).execute(dispatcher.jobs[0])
        assert result.status is BackgroundRunExecutionStatus.FAILED
        assert model.calls == 0
        async with factory() as db:
            stored = await db.get(WorkflowRun, dispatcher.jobs[0].run_id)
            assert stored is not None
            assert stored.error["message"] == "Knowledge Agent execution failed."
    finally:
        await cleanup(factory, scope)


@pytest.mark.anyio
async def test_cross_workspace_knowledge_is_denied(atomic7_factory):
    factory = atomic7_factory
    own = await create_scope(factory)
    foreign = await create_scope(factory)
    model = ScriptedModel()
    dispatcher = RecordingDispatcher()
    try:
        await configure_workflow(factory, own, base_id=foreign.knowledge_base_id)
        await submit(factory, own, dispatcher)
        result = await BackgroundRunExecutor(
            factory, engine(factory, model, []), lease_duration=LEASE
        ).execute(dispatcher.jobs[0])
        assert result.status is BackgroundRunExecutionStatus.FAILED
        assert model.calls == 0
    finally:
        await cleanup(factory, own)
        await cleanup(factory, foreign)


@pytest.mark.anyio
async def test_model_without_tool_call_persists_no_evidence(atomic7_factory):
    factory = atomic7_factory
    scope = await create_scope(factory)
    model = ScriptedModel(search=False)
    dispatcher = RecordingDispatcher()
    try:
        await configure_workflow(factory, scope)
        await submit(factory, scope, dispatcher)
        result = await BackgroundRunExecutor(
            factory, engine(factory, model, []), lease_duration=LEASE
        ).execute(dispatcher.jobs[0])
        assert result.status is BackgroundRunExecutionStatus.COMPLETED
        async with factory() as db:
            stored = await db.get(WorkflowRun, dispatcher.jobs[0].run_id)
            assert stored is not None
            assert stored.node_outputs["agent"]["status"] == "no_evidence"
            assert stored.node_outputs["agent"]["sources"] == []
    finally:
        await cleanup(factory, scope)


@pytest.mark.anyio
async def test_approval_resume_keeps_submitter_identity(atomic7_factory):
    factory = atomic7_factory
    scope = await create_scope(factory)
    model = ScriptedModel()
    dispatcher = RecordingDispatcher()
    workflow_engine = engine(factory, model, [])
    try:
        await configure_workflow(factory, scope, approval=True)
        created = await submit(factory, scope, dispatcher)
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
            assert stored is not None
            assert stored.status == "completed"
            assert stored.actor_user_id == scope.actor_id
            assert stored.node_outputs["agent"]["status"] == "answered"
    finally:
        await cleanup(factory, scope)


@pytest.mark.anyio
async def test_historical_run_without_actor_fails_closed(atomic7_factory):
    factory = atomic7_factory
    scope = await create_scope(factory)
    model = ScriptedModel()
    try:
        graph = await configure_workflow(factory, scope)
        run_id = uuid4()
        async with factory() as db, db.begin():
            db.add(
                WorkflowRun(
                    id=run_id,
                    workflow_id=scope.workflow_id,
                    workflow_revision=1,
                    actor_user_id=None,
                    definition_snapshot=serialize_workflow_graph(graph),
                    status="pending",
                    input={"question": "must not leak"},
                )
            )
        result = await BackgroundRunExecutor(
            factory, engine(factory, model, []), lease_duration=LEASE
        ).execute(WorkflowExecutionJob(run_id))
        assert result.status is BackgroundRunExecutionStatus.FAILED
        assert model.calls == 0
        async with factory() as db:
            stored = await db.get(WorkflowRun, run_id)
            assert stored is not None
            assert stored.error["message"] == "Knowledge Agent requires trusted run identity."
    finally:
        await cleanup(factory, scope)


@pytest.mark.anyio
async def test_uncommitted_agent_step_reexecutes_after_lease_expiry(atomic7_factory):
    factory = atomic7_factory
    scope = await create_scope(factory)
    dispatcher = RecordingDispatcher()
    try:
        await configure_workflow(factory, scope)
        await submit(factory, scope, dispatcher)
        job = dispatcher.jobs[0]
        with pytest.raises(SimulatedProcessCrash):
            await BackgroundRunExecutor(
                factory, engine(factory, CrashingModel(), []), lease_duration=LEASE
            ).execute(job)
        async with factory() as db, db.begin():
            await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == job.run_id)
                .values(execution_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
            )
        model = ScriptedModel()
        recovered = await BackgroundRunExecutor(
            factory, engine(factory, model, []), lease_duration=LEASE
        ).execute(job)
        assert recovered.status is BackgroundRunExecutionStatus.COMPLETED
        assert model.calls == 2
        async with factory() as db:
            stored = await db.get(WorkflowRun, job.run_id)
            assert stored is not None
            assert stored.node_outputs["agent"]["status"] == "answered"
    finally:
        await cleanup(factory, scope)
