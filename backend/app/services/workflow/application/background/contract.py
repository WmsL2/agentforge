"""Contracts for dispatching background workflow execution."""

from typing import Protocol

from app.services.workflow.application.background.domain import WorkflowExecutionJob


class WorkflowExecutionDispatcher(Protocol):
    """Submits workflow execution jobs to a background mechanism."""

    async def dispatch(
        self,
        job: WorkflowExecutionJob,
    ) -> None: ...
