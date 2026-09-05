"""Adapt AGENT workflow nodes to the Agent Runtime SPI."""

from collections.abc import Mapping

from app.services.agent_runtime import (
    AgentExecutionRequest,
    AgentRunner,
    AgentRuntimeError,
)
from app.services.workflow.definition.model.domain import WorkflowNode, WorkflowNodeKind
from app.services.workflow.execution.executor.contract import (
    NodeExecutionContext,
    NodeExecutionResult,
)


class AgentNodeExecutor:
    """Execute one AGENT node through a configured Agent Runtime runner."""

    def __init__(self, runners: Mapping[str, AgentRunner]) -> None:
        self._runners = dict(runners)

    async def execute(
        self,
        node: WorkflowNode,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        if node.kind is not WorkflowNodeKind.AGENT:
            raise RuntimeError("AgentNodeExecutor only supports AGENT workflow nodes.")

        runner_name = node.config["runner"]
        runner = self._runners.get(runner_name)
        if runner is None:
            raise AgentRuntimeError(
                code="runner_not_configured",
                message=f"Agent runner {runner_name!r} is not configured.",
            )

        agent_result = await runner.run(
            AgentExecutionRequest(
                instruction=node.config["instruction"],
                input=dict(context.upstream_outputs),
                model=node.config.get("model"),
            )
        )
        return NodeExecutionResult(
            output=agent_result.output,
            metadata=dict(agent_result.metadata),
        )
