"""Integration tests for WorkflowEngine through the Agent Runtime bridge."""

import asyncio
from uuid import uuid4

from app.services.agent_runtime import AgentExecutionRequest, AgentExecutionResult
from app.services.workflow import (
    AgentNodeExecutor,
    DeterministicNodeExecutor,
    DispatchingNodeExecutor,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowEngine,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowRun,
    WorkflowRunStatus,
)


class FakeAgentRunner:
    def __init__(
        self, result: AgentExecutionResult | None = None, error: Exception | None = None
    ) -> None:
        self.requests: list[AgentExecutionRequest] = []
        self._result = result or AgentExecutionResult(output={"answer": 42})
        self._error = error

    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return self._result


def workflow(
    nodes: tuple[WorkflowNode, ...], edges: tuple[WorkflowEdge, ...]
) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=uuid4(), name="Agent bridge", entry_node_id="start", nodes=nodes, edges=edges
    )


def run(input: dict[str, object] | None = None) -> WorkflowRun:
    return WorkflowRun(id=uuid4(), workflow_id=uuid4(), workflow_revision=1, input=input or {})


def engine(runner: FakeAgentRunner) -> WorkflowEngine:
    return WorkflowEngine(
        DispatchingNodeExecutor(
            deterministic_executor=DeterministicNodeExecutor(),
            agent_executor=AgentNodeExecutor({"langgraph": runner}),
        )
    )


def test_engine_executes_agent_node_and_records_output() -> None:
    runner = FakeAgentRunner(AgentExecutionResult(output={"answer": 42}))
    definition = workflow(
        (
            WorkflowNode("start", WorkflowNodeKind.START),
            WorkflowNode(
                "agent",
                WorkflowNodeKind.AGENT,
                {"runner": "langgraph", "instruction": "Analyze input."},
            ),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        (WorkflowEdge("start-agent", "start", "agent"), WorkflowEdge("agent-end", "agent", "end")),
    )
    workflow_run = run({"question": "What is 6 times 7?"})

    asyncio.run(engine(runner).execute(definition, workflow_run))

    assert workflow_run.status is WorkflowRunStatus.COMPLETED
    assert runner.requests[0].input == {"start": {"question": "What is 6 times 7?"}}
    assert workflow_run.node_outputs["agent"] == {"answer": 42}
    assert workflow_run.node_outputs["end"] == {"agent": {"answer": 42}}
    assert workflow_run.output == {"end": {"agent": {"answer": 42}}}


def test_engine_passes_only_direct_fan_in_outputs_to_agent() -> None:
    runner = FakeAgentRunner()
    definition = workflow(
        (
            WorkflowNode("start", WorkflowNodeKind.START),
            WorkflowNode("value_a", WorkflowNodeKind.VALUE, {"value": "A"}),
            WorkflowNode("value_b", WorkflowNodeKind.VALUE, {"value": "B"}),
            WorkflowNode(
                "agent",
                WorkflowNodeKind.AGENT,
                {"runner": "langgraph", "instruction": "Compare values."},
            ),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        (
            WorkflowEdge("start-a", "start", "value_a"),
            WorkflowEdge("start-b", "start", "value_b"),
            WorkflowEdge("a-agent", "value_a", "agent"),
            WorkflowEdge("b-agent", "value_b", "agent"),
            WorkflowEdge("agent-end", "agent", "end"),
        ),
    )

    asyncio.run(engine(runner).execute(definition, run()))

    assert runner.requests[0].input == {"value_a": "A", "value_b": "B"}


def test_engine_marks_run_failed_when_agent_runner_raises() -> None:
    runner = FakeAgentRunner(error=RuntimeError("agent exploded"))
    definition = workflow(
        (
            WorkflowNode("start", WorkflowNodeKind.START),
            WorkflowNode(
                "agent",
                WorkflowNodeKind.AGENT,
                {"runner": "langgraph", "instruction": "Run."},
            ),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        (WorkflowEdge("start-agent", "start", "agent"), WorkflowEdge("agent-end", "agent", "end")),
    )
    workflow_run = run()

    asyncio.run(engine(runner).execute(definition, workflow_run))

    assert workflow_run.status is WorkflowRunStatus.FAILED
    assert workflow_run.error is not None
    assert workflow_run.error.code == "node_execution_failed"
    assert workflow_run.error.message == "agent exploded"
    assert workflow_run.error.node_id == "agent"
