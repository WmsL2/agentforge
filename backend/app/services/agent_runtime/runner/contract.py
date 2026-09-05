"""Framework-agnostic runner service-provider interface."""

from typing import Protocol

from app.services.agent_runtime.execution.domain import AgentExecutionRequest, AgentExecutionResult


class AgentRunner(Protocol):
    """Run one agent execution request asynchronously."""

    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Run ``request`` and return its result."""
