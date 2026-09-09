"""Tests for the LangGraph Tool Platform adapter."""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from app.services.agent_runtime.runner.implementations import LangGraphToolAdapter
from app.services.tool import (
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionService,
    ToolRegistry,
)
from app.services.tool.definition.validation import ToolSchemaValidator


class RecordingExecutor:
    """A ToolExecutor fake that records adapter-originated requests."""

    def __init__(self, output: Any = None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.received_request: ToolExecutionRequest | None = None

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.received_request = request
        if self.error is not None:
            raise self.error
        return ToolExecutionResult(output=self.output)


class _ToolState(TypedDict):
    """Minimal graph state for ToolNode compatibility coverage."""

    messages: list[Any]


def _add_definition() -> ToolDefinition:
    return ToolDefinition(
        name="add",
        description="Add two integers.",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    )


def _service(definition: ToolDefinition, executor: RecordingExecutor) -> ToolExecutionService:
    registry = ToolRegistry()
    registry.register(definition, executor)
    return ToolExecutionService(registry, ToolSchemaValidator())


def test_adapt_preserves_definition_identity_and_json_schema() -> None:
    definition = _add_definition()
    tool = LangGraphToolAdapter(_service(definition, RecordingExecutor())).adapt(definition)

    assert tool.name == "add"
    assert tool.description == "Add two integers."
    assert tool.args == {
        "a": {"type": "integer"},
        "b": {"type": "integer"},
    }


@pytest.mark.anyio
async def test_adapter_executes_only_through_tool_execution_service() -> None:
    definition = _add_definition()
    executor = RecordingExecutor(output=3)
    tool = LangGraphToolAdapter(_service(definition, executor)).adapt(definition)

    output = await tool.ainvoke({"a": 1, "b": 2})

    assert output == 3
    assert executor.received_request is not None
    assert executor.received_request.tool_name == "add"
    assert executor.received_request.arguments == {"a": 1, "b": 2}


@pytest.mark.anyio
async def test_adapter_preserves_tool_platform_validation_and_skips_executor() -> None:
    definition = _add_definition()
    executor = RecordingExecutor(output=3)
    tool = LangGraphToolAdapter(_service(definition, executor)).adapt(definition)

    with pytest.raises(ToolExecutionError) as error_info:
        await tool.ainvoke({"a": "one", "b": 2})

    assert error_info.value.code == "invalid_arguments"
    assert executor.received_request is None


@pytest.mark.anyio
async def test_adapter_uses_service_for_unknown_registration() -> None:
    definition = ToolDefinition(name="missing", description="Missing tool.", input_schema={"type": "object"})
    tool = LangGraphToolAdapter(ToolExecutionService(ToolRegistry(), ToolSchemaValidator())).adapt(definition)

    with pytest.raises(ToolExecutionError) as error_info:
        await tool.ainvoke({})

    assert error_info.value.code == "tool_not_found"


@pytest.mark.anyio
async def test_adapter_preserves_structured_tool_output() -> None:
    definition = _add_definition()
    output = {"date": "2026-09-09", "time": "10:00:00"}
    tool = LangGraphToolAdapter(_service(definition, RecordingExecutor(output=output))).adapt(definition)

    result = await tool.ainvoke({"a": 1, "b": 2})

    assert result is output


@pytest.mark.anyio
async def test_adapter_preserves_tool_execution_error_identity() -> None:
    definition = _add_definition()
    original_error = ToolExecutionError(
        code="upstream_unavailable",
        message="provider unavailable",
        retryable=True,
    )
    tool = LangGraphToolAdapter(_service(definition, RecordingExecutor(error=original_error))).adapt(
        definition
    )

    with pytest.raises(ToolExecutionError) as error_info:
        await tool.ainvoke({"a": 1, "b": 2})

    assert error_info.value is original_error


@pytest.mark.anyio
async def test_adapter_tool_is_compatible_with_langgraph_tool_node() -> None:
    definition = _add_definition()
    executor = RecordingExecutor(output=3)
    tool = LangGraphToolAdapter(_service(definition, executor)).adapt(definition)
    tool_node = ToolNode([tool])
    graph = StateGraph(_ToolState)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)

    result = await graph.compile().ainvoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "add",
                            "args": {"a": 1, "b": 2},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
    )

    message = result["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call-1"
    assert message.name == "add"
    assert message.content == "3"
    assert executor.received_request is not None
