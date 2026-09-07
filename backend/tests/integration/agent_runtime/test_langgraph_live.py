"""Strictly opt-in live smoke coverage for the LangGraph Agent Runtime runner."""

import os

import pytest

from app.core.config import settings
from app.services.agent_runtime import AgentExecutionRequest, AgentExecutionResult
from app.services.agent_runtime.runner.implementations import LangGraphAgentRunner

_LIVE_SMOKE_ENV = "AGENTFORGE_RUN_LIVE_AGENT_SMOKE"
_LIVE_MODEL_ENV = "AGENTFORGE_LIVE_AGENT_MODEL"
_MARKER = "AGENTFORGE_LIVE_OK"


@pytest.mark.anyio
async def test_langgraph_agent_runner_live_smoke() -> None:
    """Exercise the real LangGraph and OpenAI path only when explicitly enabled."""
    if os.getenv(_LIVE_SMOKE_ENV) != "1":
        pytest.skip(f"Set {_LIVE_SMOKE_ENV}=1 to run the live Agent Runtime smoke test.")
    if not settings.LLM_API_KEY:
        pytest.fail(
            "LLM_API_KEY is required for the live OpenAI-compatible Agent Runtime smoke test."
        )

    runner = LangGraphAgentRunner()
    request = AgentExecutionRequest(
        instruction=(f"Return a short response containing the literal marker {_MARKER}."),
        input="Run the AgentForge live runtime smoke test.",
        model=os.getenv(_LIVE_MODEL_ENV) or None,
    )

    result = await runner.run(request)

    assert isinstance(result, AgentExecutionResult)
    assert result.output is not None
    assert _MARKER in str(result.output)
