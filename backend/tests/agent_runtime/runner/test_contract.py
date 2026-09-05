"""Tests for the agent runner service-provider interface."""

import asyncio

from app.services.agent_runtime import AgentExecutionRequest, AgentExecutionResult, AgentRunner


class FakeAgentRunner:
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        return AgentExecutionResult(output=request.input, metadata={"runner": "fake"})


async def _run_request(runner: AgentRunner, request: AgentExecutionRequest) -> AgentExecutionResult:
    return await runner.run(request)


def test_runner_uses_structural_typing() -> None:
    result = asyncio.run(
        _run_request(
            FakeAgentRunner(),
            AgentExecutionRequest(instruction="Echo", input={"value": "hello"}),
        )
    )

    assert result.output == {"value": "hello"}
    assert result.metadata == {"runner": "fake"}
