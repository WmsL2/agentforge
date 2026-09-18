"""Adapt AGENT workflow nodes to the Agent Runtime SPI."""

from collections.abc import Mapping
from contextlib import suppress

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
from app.services.workflow.execution.observability.domain import TraceEventKind
from app.services.workflow.execution.observability.observer import (
    NoOpWorkflowExecutionObserver,
    WorkflowExecutionObserver,
    WorkflowObservationContext,
)


class AgentNodeExecutor:
    """Execute one AGENT node through a configured Agent Runtime runner."""

    def __init__(
        self,
        runners: Mapping[str, AgentRunner],
        *,
        observer: WorkflowExecutionObserver | None = None,
    ) -> None:
        self._runners = dict(runners)
        self._observer = observer or NoOpWorkflowExecutionObserver()

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

        request = AgentExecutionRequest(
            instruction=node.config["instruction"],
            input=dict(context.upstream_outputs),
            model=node.config.get("model"),
            trace_run_id=context.run_id,
            trace_step_id=context.step_id,
        )
        observation = (
            None
            if context.step_id is None
            else WorkflowObservationContext(run_id=context.run_id, step_id=context.step_id)
        )
        base_payload = {
            "node_id": node.id,
            "runner": runner_name,
            "model": node.config.get("model"),
        }
        if observation is not None:
            with suppress(Exception):
                await self._observer.record_event(
                    observation, kind=TraceEventKind.AGENT_STARTED, payload=base_payload
                )
        try:
            agent_result = await runner.run(request)
        except Exception as error:
            if observation is not None:
                with suppress(Exception):
                    await self._observer.record_event(
                        observation,
                        kind=TraceEventKind.AGENT_FAILED,
                        payload={**base_payload, "error": _agent_error_payload(error)},
                    )
            raise
        if observation is not None:
            with suppress(Exception):
                await self._observer.record_event(
                    observation,
                    kind=TraceEventKind.AGENT_COMPLETED,
                    payload={**base_payload, "metadata": dict(agent_result.metadata)},
                )
        return NodeExecutionResult(
            output=agent_result.output,
            metadata=dict(agent_result.metadata),
        )


def _agent_error_payload(error: Exception) -> dict[str, object]:
    if isinstance(error, AgentRuntimeError):
        return {"code": error.code, "message": error.message, "retryable": error.retryable}
    return {
        "code": "agent_execution_failed",
        "message": str(error) or type(error).__name__,
        "retryable": False,
    }
