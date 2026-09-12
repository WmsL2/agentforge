"""Offline end-to-end tests against a real stdio MCP server subprocess."""

import sys
from pathlib import Path

import anyio
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.api.deps import get_langgraph_agent_runner
from app.composition.tool_platform import open_tool_platform
from app.core.config import MCPStdioServerSettings
from app.integrations.mcp.transport import open_stdio_mcp_client
from app.services.agent_runtime import AgentExecutionRequest
from app.services.agent_runtime.runner.implementations import LangGraphAgentRunner
from app.services.tool import ToolExecutionError, ToolExecutionRequest, ToolExecutionService
from app.services.tool.definition.validation import ToolSchemaValidator

SERVER_PATH = (Path(__file__).parent / "fixtures" / "stdio_server.py").resolve()
TEST_ENVIRONMENT = {"AGENTFORGE_MCP_TEST_VALUE": "connected"}


def _server_settings() -> MCPStdioServerSettings:
    return MCPStdioServerSettings(
        namespace="fixture",
        command=sys.executable,
        args=[str(SERVER_PATH)],
        env=TEST_ENVIRONMENT,
    )


class FakeChatModel:
    """Offline model used to drive a real MCP ToolNode execution loop."""

    def __init__(self) -> None:
        self.bound_tools = []
        self.calls = []
        self.responses = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "fixture__multiply",
                        "args": {"left": 6, "right": 7},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="The result is 42."),
        ]

    def bind_tools(self, tools):
        self.bound_tools.append(tools)
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


@pytest.mark.anyio
async def test_real_stdio_sdk_client_lists_and_calls_fixture_tools() -> None:
    with anyio.fail_after(20):
        async with open_stdio_mcp_client(
            command=sys.executable,
            args=[str(SERVER_PATH)],
            env=TEST_ENVIRONMENT,
        ) as client:
            descriptors = await client.list_tools()
            result = await client.call_tool("multiply", {"left": 6, "right": 7})

    assert {descriptor.name for descriptor in descriptors} >= {"multiply", "read_env", "always_fail"}
    assert result.output == {"value": 42}
    assert result.is_error is False


@pytest.mark.anyio
async def test_real_tool_platform_discovers_executes_and_propagates_server_results() -> None:
    with anyio.fail_after(20):
        async with open_tool_platform((_server_settings(),)) as registry:
            definitions = registry.definitions()
            service = ToolExecutionService(registry, ToolSchemaValidator())
            multiply = await service.execute(
                ToolExecutionRequest("fixture__multiply", {"left": 6, "right": 7})
            )
            environment = await service.execute(
                ToolExecutionRequest(
                    "fixture__read_env",
                    {"name": "AGENTFORGE_MCP_TEST_VALUE"},
                )
            )
            with pytest.raises(ToolExecutionError) as error_info:
                await service.execute(
                    ToolExecutionRequest(
                        "fixture__always_fail",
                        {"message": "expected-mcp-failure"},
                    )
                )

    assert {definition.name for definition in definitions} >= {
        "current_datetime",
        "fixture__multiply",
        "fixture__read_env",
        "fixture__always_fail",
    }
    assert multiply.output == {"value": 42}
    assert environment.output == "connected"
    assert error_info.value.code == "mcp_tool_execution_failed"
    assert error_info.value.retryable is False
    assert "expected-mcp-failure" in error_info.value.message


@pytest.mark.anyio
async def test_real_mcp_tool_completes_the_dynamic_langgraph_agent_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeChatModel()
    monkeypatch.setattr(
        LangGraphAgentRunner,
        "_create_model",
        staticmethod(lambda _model_name: model),
    )

    with anyio.fail_after(20):
        async with open_tool_platform((_server_settings(),)) as registry:
            service = ToolExecutionService(registry, ToolSchemaValidator())
            runner = get_langgraph_agent_runner(registry, service)
            result = await runner.run(
                AgentExecutionRequest(
                    instruction="Multiply the numbers using the available tool.",
                    input={"left": 6, "right": 7},
                )
            )

    bound_names = [tool.name for tool in model.bound_tools[0]]
    tool_message = next(message for message in model.calls[1] if isinstance(message, ToolMessage))
    assert {"current_datetime", "fixture__multiply", "fixture__read_env", "fixture__always_fail"} <= set(
        bound_names
    )
    assert tool_message.name == "fixture__multiply"
    assert tool_message.tool_call_id == "call-1"
    assert "42" in str(tool_message.content)
    assert result.output == "The result is 42."
