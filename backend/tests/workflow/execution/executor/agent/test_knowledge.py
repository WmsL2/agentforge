"""Knowledge-enhanced AGENT isolation and safe output contracts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.agent_runtime import AgentExecutionResult, AgentRuntimeError
from app.services.agent_runtime.execution.trace_context import bind_trace_context
from app.services.knowledge.retrieval_service import KnowledgeSearchItem, KnowledgeSearchResult
from app.services.tool import ToolDefinition, ToolRegistry
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor
from app.services.workflow import (
    AgentNodeExecutor,
    NodeExecutionContext,
    WorkflowNode,
    WorkflowNodeKind,
)
from app.services.workflow.execution.executor.agent.knowledge import (
    WorkflowAgentKnowledgeComposition,
)


class FakeRunner:
    def __init__(self, tools, output, *, call_knowledge=True, failure=None, calls=1):
        self.tools = {tool.name: tool for tool in tools}
        self.output = output
        self.call_knowledge = call_knowledge
        self.failure = failure
        self.calls = calls
        self.closed = False

    async def run(self, request):
        with bind_trace_context(request.trace_run_id, request.trace_step_id):
            if self.call_knowledge:
                for _ in range(self.calls):
                    await self.tools["knowledge_search"].ainvoke({"query": "question", "top_k": 5})
        if self.failure:
            raise self.failure
        return AgentExecutionResult(output=self.output)

    async def aclose(self):
        self.closed = True


def setup(output="answer", *, call_knowledge=True, failure=None, calls=1, tool_observer=None):
    base_id = uuid4()
    item = KnowledgeSearchItem(
        chunk_id=uuid4(),
        document_id=uuid4(),
        knowledge_base_id=base_id,
        filename="source.pdf",
        chunk_index=0,
        content="evidence",
        start_offset=0,
        end_offset=8,
        page_start=1,
        page_end=1,
        similarity_score=0.9,
    )
    retrieval = SimpleNamespace(
        authorize_scope=AsyncMock(),
        search=AsyncMock(return_value=KnowledgeSearchResult("question", [item], 1, "model")),
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("current_datetime", "Clock", {"type": "object", "properties": {}}),
        NativeCallableToolExecutor(lambda: "now"),
    )
    runners = []

    def factory(tools, limit):
        runner = FakeRunner(
            tools, output, call_knowledge=call_knowledge, failure=failure, calls=calls
        )
        runners.append(runner)
        return runner

    composition = WorkflowAgentKnowledgeComposition(
        retrieval,
        registry,
        factory,
        tool_observer=tool_observer,
        timeout_seconds=0.2,
        maximum_calls=2,
    )
    executor = AgentNodeExecutor(
        {"langgraph": SimpleNamespace(run=AsyncMock())}, knowledge=composition
    )
    node = WorkflowNode(
        "agent",
        WorkflowNodeKind.AGENT,
        {"runner": "langgraph", "instruction": "Answer", "knowledge_base_id": str(base_id)},
    )
    context = NodeExecutionContext(
        run_id=uuid4(),
        workflow_input={},
        upstream_outputs={},
        node_outputs={},
        workspace_id=uuid4(),
        actor_user_id=uuid4(),
    )
    return executor, node, context, retrieval, registry, runners, item


@pytest.mark.anyio
async def test_evidence_and_base_tools_are_isolated_and_runner_closed():
    executor, node, context, retrieval, registry, runners, item = setup()
    result = await executor.execute(node, context)
    assert result.output["status"] == "answered"
    assert result.output["sources"][0]["chunk_id"] == str(item.chunk_id)
    assert set(runners[0].tools) == {"current_datetime", "knowledge_search"}
    assert runners[0].closed
    assert [d.name for d in registry.definitions()] == ["current_datetime"]
    retrieval.authorize_scope.assert_awaited_once_with(
        context.workspace_id, item.knowledge_base_id, context.actor_user_id
    )


@pytest.mark.anyio
async def test_mcp_registration_coexists_without_closing_shared_client():
    executor, node, context, _, registry, runners, _ = setup()
    shared_mcp = SimpleNamespace(execute=AsyncMock(), aclose=AsyncMock())
    registry.register(
        ToolDefinition("mcp_lookup", "MCP lookup", {"type": "object", "properties": {}}),
        shared_mcp,
    )
    await executor.execute(node, context)
    assert set(runners[0].tools) == {"current_datetime", "mcp_lookup", "knowledge_search"}
    shared_mcp.aclose.assert_not_awaited()


@pytest.mark.anyio
async def test_no_tool_call_and_empty_evidence_return_no_evidence():
    executor, node, context, _, _, _, _ = setup(call_knowledge=False)
    assert (await executor.execute(node, context)).output["status"] == "no_evidence"
    executor, node, context, retrieval, _, _, _ = setup()
    retrieval.search.return_value = KnowledgeSearchResult("question", [], 0, "model")
    assert (await executor.execute(node, context)).output["status"] == "no_evidence"


@pytest.mark.anyio
async def test_structured_text_and_invalid_response():
    executor, node, context, _, _, _, _ = setup([{"type": "text", "text": "grounded"}])
    assert (await executor.execute(node, context)).output["answer"] == "grounded"
    executor, node, context, _, _, _, _ = setup([{"type": "image", "url": "secret"}])
    with pytest.raises(AgentRuntimeError, match="invalid response"):
        await executor.execute(node, context)


@pytest.mark.anyio
async def test_identity_and_name_collision_fail_before_llm():
    executor, node, context, retrieval, registry, runners, _ = setup()
    context = NodeExecutionContext(context.run_id, {}, {}, {})
    with pytest.raises(AgentRuntimeError, match="trusted run identity"):
        await executor.execute(node, context)
    assert not runners
    registry.register(
        ToolDefinition("knowledge_search", "Collision", {}),
        NativeCallableToolExecutor(lambda: None),
    )
    with pytest.raises(AgentRuntimeError, match="tool name"):
        await executor.execute(node, NodeExecutionContext(uuid4(), {}, {}, {}, uuid4(), uuid4()))
    retrieval.authorize_scope.assert_not_awaited()


@pytest.mark.anyio
async def test_concurrent_runs_have_distinct_tools_and_limits():
    executor, node, context, retrieval, _, runners, _ = setup()
    other = NodeExecutionContext(uuid4(), {}, {}, {}, uuid4(), uuid4())
    await asyncio.gather(executor.execute(node, context), executor.execute(node, other))
    assert runners[0].tools["knowledge_search"] is not runners[1].tools["knowledge_search"]
    assert retrieval.search.await_count == 2


@pytest.mark.anyio
async def test_tool_observer_receives_run_and_step_identity():
    observer = SimpleNamespace(
        start_tool=AsyncMock(), complete_tool=AsyncMock(), fail_tool=AsyncMock()
    )
    executor, node, context, _, _, _, _ = setup(tool_observer=observer)
    context = NodeExecutionContext(
        context.run_id, {}, {}, {}, context.workspace_id, context.actor_user_id, uuid4()
    )
    await executor.execute(node, context)
    request = observer.start_tool.await_args.args[0]
    assert request.trace_run_id == context.run_id
    assert request.trace_step_id == context.step_id
    observer.complete_tool.assert_awaited_once()


@pytest.mark.anyio
async def test_tool_failure_trace_excludes_raw_database_error():
    observer = SimpleNamespace(
        start_tool=AsyncMock(), complete_tool=AsyncMock(), fail_tool=AsyncMock()
    )
    executor, node, context, retrieval, _, _, _ = setup(tool_observer=observer)
    retrieval.search.side_effect = RuntimeError("postgresql://secret-password")
    with pytest.raises(AgentRuntimeError):
        await executor.execute(node, context)
    recorded_error = observer.fail_tool.await_args.args[1]
    assert "secret-password" not in recorded_error.message
    assert recorded_error.code == "knowledge_agent_tool_failed"


@pytest.mark.anyio
async def test_tool_call_limit_and_search_binding():
    executor, node, context, retrieval, _, runners, item = setup(calls=3)
    with pytest.raises(AgentRuntimeError, match="execution failed"):
        await executor.execute(node, context)
    assert retrieval.search.await_count == 2
    retrieval.search.assert_any_await(
        context.workspace_id,
        item.knowledge_base_id,
        context.actor_user_id,
        "question",
        5,
        None,
    )
    assert runners[0].closed


@pytest.mark.anyio
async def test_model_and_retrieval_errors_are_redacted_and_close_runner():
    executor, node, context, _, _, runners, _ = setup(failure=RuntimeError("provider secret token"))
    with pytest.raises(AgentRuntimeError) as caught:
        await executor.execute(node, context)
    assert "secret" not in caught.value.message
    assert runners[0].closed

    executor, node, context, retrieval, _, runners, _ = setup()
    retrieval.search.side_effect = RuntimeError("database connection secret")
    with pytest.raises(AgentRuntimeError) as caught:
        await executor.execute(node, context)
    assert "secret" not in caught.value.message
    assert runners[0].closed


@pytest.mark.anyio
async def test_preflight_and_model_timeout():
    executor, node, context, retrieval, _, runners, _ = setup()

    async def blocked(*args):
        await asyncio.sleep(1)

    retrieval.authorize_scope.side_effect = blocked
    with pytest.raises(AgentRuntimeError, match="timed out"):
        await executor.execute(node, context)
    assert not runners

    executor, node, context, _, _, runners, _ = setup()

    class BlockingRunner(FakeRunner):
        async def run(self, request):
            await asyncio.sleep(1)

    executor._knowledge._runner_factory = lambda tools, limit: (
        runners.append(BlockingRunner(tools, "answer")) or runners[-1]
    )
    with pytest.raises(AgentRuntimeError, match="timed out"):
        await executor.execute(node, context)
    assert runners[0].closed
