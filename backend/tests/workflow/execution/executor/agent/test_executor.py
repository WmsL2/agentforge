"""Tests for the AGENT workflow node execution adapter."""

import asyncio
from uuid import uuid4

import pytest

from app.services.agent_runtime import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentRuntimeError,
)
from app.services.workflow import (
    AgentNodeExecutor,
    NodeExecutionContext,
    WorkflowNode,
    WorkflowNodeKind,
)


class FakeAgentRunner:
    def __init__(self, result: AgentExecutionResult | None = None) -> None:
        self.requests: list[AgentExecutionRequest] = []
        self._result = result or AgentExecutionResult(output={"answer": 42})

    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.requests.append(request)
        return self._result


def context(upstream_outputs: dict[str, object]) -> NodeExecutionContext:
    return NodeExecutionContext(
        run_id=uuid4(),
        workflow_input={"request": "workflow input"},
        upstream_outputs=upstream_outputs,
        node_outputs={"unrelated": "not passed"},
    )


def agent_node(**config: object) -> WorkflowNode:
    return WorkflowNode(
        id="agent",
        kind=WorkflowNodeKind.AGENT,
        config={"runner": "langgraph", "instruction": "Analyze input.", **config},
    )


def test_agent_node_executor_maps_request_and_result() -> None:
    runner = FakeAgentRunner(AgentExecutionResult(output={"answer": 42}, metadata={"tokens": 3}))
    executor = AgentNodeExecutor({"langgraph": runner})

    result = asyncio.run(
        executor.execute(
            agent_node(model="gpt-5-mini"),
            context({"value_a": "A", "value_b": "B"}),
        )
    )

    assert runner.requests == [
        AgentExecutionRequest(
            instruction="Analyze input.",
            input={"value_a": "A", "value_b": "B"},
            model="gpt-5-mini",
        )
    ]
    assert runner.requests[0].metadata == {}
    assert result.output == {"answer": 42}
    assert result.metadata == {"tokens": 3}
    assert isinstance(result.metadata, dict)


def test_agent_node_executor_uses_none_for_missing_model() -> None:
    runner = FakeAgentRunner()
    executor = AgentNodeExecutor({"langgraph": runner})

    asyncio.run(executor.execute(agent_node(), context({"start": {"request": "hello"}})))

    assert runner.requests[0].model is None
    assert runner.requests[0].input == {"start": {"request": "hello"}}


def test_agent_node_executor_snapshots_runner_mapping() -> None:
    original = FakeAgentRunner(AgentExecutionResult(output="original"))
    replacement = FakeAgentRunner(AgentExecutionResult(output="replacement"))
    runners = {"langgraph": original}
    executor = AgentNodeExecutor(runners)
    runners["langgraph"] = replacement

    result = asyncio.run(executor.execute(agent_node(), context({})))

    assert result.output == "original"
    assert len(original.requests) == 1
    assert replacement.requests == []


def test_agent_node_executor_rejects_missing_configured_runner() -> None:
    with pytest.raises(AgentRuntimeError) as error:
        asyncio.run(AgentNodeExecutor({}).execute(agent_node(), context({})))

    assert error.value.code == "runner_not_configured"
    assert "langgraph" in error.value.message


def test_agent_node_executor_rejects_non_agent_node_misuse() -> None:
    with pytest.raises(RuntimeError, match="only supports AGENT"):
        asyncio.run(
            AgentNodeExecutor({}).execute(
                WorkflowNode(id="value", kind=WorkflowNodeKind.VALUE),
                context({}),
            )
        )
