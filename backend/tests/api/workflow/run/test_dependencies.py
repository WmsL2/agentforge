"""Production workflow-engine dependency composition tests."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.api.deps import (
    get_langgraph_agent_runner,
    get_tool_execution_service,
    get_tool_registry,
    get_workflow_engine,
)
from app.composition.tool_platform import open_tool_platform
from app.services.agent_runtime import AgentExecutionRequest, AgentExecutionResult
from app.services.agent_runtime.runner.implementations import LangGraphAgentRunner
from app.services.workflow import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowRun,
    WorkflowRunStatus,
)


class FakeAgentRunner:
    """Offline AgentRunner replacement that records requests."""

    def __init__(self, output: object | None = None) -> None:
        self.requests: list[AgentExecutionRequest] = []
        self._output = {"answer": "analyzed"} if output is None else output

    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.requests.append(request)
        return AgentExecutionResult(output=self._output)


def _definition(
    nodes: tuple[WorkflowNode, ...], edges: tuple[WorkflowEdge, ...]
) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=uuid4(),
        name="Dependency composition",
        entry_node_id="start",
        nodes=nodes,
        edges=edges,
    )


def _run(input: dict[str, object]) -> WorkflowRun:
    return WorkflowRun(id=uuid4(), workflow_id=uuid4(), workflow_revision=1, input=input)


def _registry():
    async def open_registry():
        async with open_tool_platform(()) as registry:
            return registry

    return asyncio.run(open_registry())


def _request_with_registry(registry):
    return SimpleNamespace(state=SimpleNamespace(tool_registry=registry))


def test_get_langgraph_agent_runner_returns_concrete_runner() -> None:
    registry = get_tool_registry(_request_with_registry(_registry()))
    runner = get_langgraph_agent_runner(registry, get_tool_execution_service(registry))

    assert isinstance(runner, LangGraphAgentRunner)


def test_production_composition_executes_current_datetime_tool_loop(
    monkeypatch,
) -> None:
    class FakeChatModel:
        def __init__(self) -> None:
            self.calls = []
            self.responses = [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "current_datetime",
                            "args": {},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Current time retrieved."),
            ]

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.calls.append(messages)
            return self.responses.pop(0)

    model = FakeChatModel()
    monkeypatch.setattr(
        LangGraphAgentRunner,
        "_create_model",
        staticmethod(lambda _model_name: model),
    )
    registry = get_tool_registry(_request_with_registry(_registry()))
    runner = get_langgraph_agent_runner(registry, get_tool_execution_service(registry))

    result = asyncio.run(
        runner.run(AgentExecutionRequest(instruction="Get the time.", input="now"))
    )

    assert result.output == "Current time retrieved."
    assert len(model.calls) == 2
    tool_message = model.calls[1][-1]
    assert tool_message.name == "current_datetime"
    assert tool_message.tool_call_id == "call-1"


def test_production_composition_executes_agent_node_with_injected_runner() -> None:
    runner = FakeAgentRunner(output={"answer": "done"})
    definition = _definition(
        (
            WorkflowNode("start", WorkflowNodeKind.START),
            WorkflowNode(
                "agent",
                WorkflowNodeKind.AGENT,
                {"runner": "langgraph", "instruction": "Analyze input."},
            ),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        (
            WorkflowEdge("start-agent", "start", "agent"),
            WorkflowEdge("agent-end", "agent", "end"),
        ),
    )
    workflow_run = _run({"question": "What is the answer?"})

    asyncio.run(get_workflow_engine(runner).execute(definition, workflow_run))

    assert workflow_run.status is WorkflowRunStatus.COMPLETED
    assert len(runner.requests) == 1
    assert runner.requests[0].input == {"start": {"question": "What is the answer?"}}
    assert workflow_run.node_outputs["agent"] == {"answer": "done"}
    assert workflow_run.node_outputs["end"] == {"agent": {"answer": "done"}}
    assert workflow_run.output == {"end": {"agent": {"answer": "done"}}}


def test_production_composition_preserves_deterministic_execution() -> None:
    runner = FakeAgentRunner()
    definition = _definition(
        (
            WorkflowNode("start", WorkflowNodeKind.START),
            WorkflowNode("value", WorkflowNodeKind.VALUE, {"value": 42}),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        (
            WorkflowEdge("start-value", "start", "value"),
            WorkflowEdge("value-end", "value", "end"),
        ),
    )
    workflow_run = _run({"ignored": True})

    asyncio.run(get_workflow_engine(runner).execute(definition, workflow_run))

    assert workflow_run.status is WorkflowRunStatus.COMPLETED
    assert workflow_run.node_outputs["value"] == 42
    assert workflow_run.node_outputs["end"] == {"value": 42}
    assert workflow_run.output == {"end": {"value": 42}}
    assert runner.requests == []
