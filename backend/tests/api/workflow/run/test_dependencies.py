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
from app.integrations.mcp import MCPToolCallResult, MCPToolExecutor
from app.services.agent_runtime import AgentExecutionRequest, AgentExecutionResult
from app.services.agent_runtime.runner.implementations import LangGraphAgentRunner
from app.services.tool import ToolDefinition, ToolRegistry
from app.services.tool.execution.executor.implementations import NativeCallableToolExecutor
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


class RecordingChatModel:
    """Offline model that records tool binding and returns queued responses."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = responses
        self.bound_tools = []

    def bind_tools(self, tools):
        self.bound_tools.append(tools)
        return self

    async def ainvoke(self, messages):
        return self.responses.pop(0)


class FakeMCPClient:
    """Offline MCP client used to verify the Agent Runtime execution path."""

    def __init__(self) -> None:
        self.received_tool_name = None
        self.received_arguments = None

    async def list_tools(self):
        return ()

    async def call_tool(self, tool_name, arguments):
        self.received_tool_name = tool_name
        self.received_arguments = arguments
        return MCPToolCallResult(output={"issue": 42})


def _runner_with_model(monkeypatch, registry: ToolRegistry, model: RecordingChatModel):
    monkeypatch.setattr(
        LangGraphAgentRunner,
        "_create_model",
        staticmethod(lambda _model_name: model),
    )
    return get_langgraph_agent_runner(registry, get_tool_execution_service(registry))


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


def test_runner_binds_all_registered_tools_in_registration_order(monkeypatch) -> None:
    registry = ToolRegistry()
    for name in ("tool_a", "tool_b", "tool_c"):
        registry.register(
            ToolDefinition(name, f"{name} description", {"type": "object"}),
            NativeCallableToolExecutor(lambda: None),
        )
    model = RecordingChatModel([AIMessage(content="Done.")])
    runner = _runner_with_model(monkeypatch, registry, model)

    result = asyncio.run(runner.run(AgentExecutionRequest(instruction="Answer.", input="input")))

    assert result.output == "Done."
    assert [tool.name for tool in model.bound_tools[0]] == ["tool_a", "tool_b", "tool_c"]


def test_runner_binds_native_and_dynamically_registered_tools(monkeypatch) -> None:
    registry = _registry()
    registry.register(
        ToolDefinition("extra_tool", "An extra tool.", {"type": "object"}),
        NativeCallableToolExecutor(lambda: None),
    )
    model = RecordingChatModel([AIMessage(content="Done.")])
    runner = _runner_with_model(monkeypatch, registry, model)

    asyncio.run(runner.run(AgentExecutionRequest(instruction="Answer.", input="input")))

    assert [tool.name for tool in model.bound_tools[0]] == ["current_datetime", "extra_tool"]


def test_runner_supports_an_empty_registry_without_binding_tools(monkeypatch) -> None:
    model = RecordingChatModel([AIMessage(content="No tools needed.")])
    runner = _runner_with_model(monkeypatch, ToolRegistry(), model)

    result = asyncio.run(runner.run(AgentExecutionRequest(instruction="Answer.", input="input")))

    assert result.output == "No tools needed."
    assert model.bound_tools == []


def test_mcp_tool_completes_the_agent_tool_loop_with_remote_name(monkeypatch) -> None:
    client = FakeMCPClient()
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "github__create_issue",
            "Create a GitHub issue.",
            {"type": "object", "properties": {"title": {"type": "string"}}},
        ),
        MCPToolExecutor(client, remote_name="create_issue"),
    )
    model = RecordingChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "github__create_issue",
                        "args": {"title": "Bug"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Issue created."),
        ]
    )
    runner = _runner_with_model(monkeypatch, registry, model)

    result = asyncio.run(runner.run(AgentExecutionRequest(instruction="Create issue.", input="Bug")))

    assert [tool.name for tool in model.bound_tools[0]] == ["github__create_issue"]
    assert client.received_tool_name == "create_issue"
    assert client.received_arguments == {"title": "Bug"}
    assert result.output == "Issue created."


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
