"""Celery adapter for the background workflow dispatch contract."""

import asyncio
from typing import Protocol

from app.services.workflow import WorkflowExecutionJob

WORKFLOW_EXECUTION_TASK = "agentforge.workflow.execute"


class CeleryTaskPublisher(Protocol):
    """Minimal Celery publishing surface used by the adapter."""

    def send_task(self, name: str, *, kwargs: dict[str, str]) -> object: ...


class CeleryWorkflowDispatcher:
    """Publish workflow jobs without blocking the request event loop."""

    def __init__(self, celery_app: CeleryTaskPublisher) -> None:
        self._celery_app = celery_app

    async def dispatch(self, job: WorkflowExecutionJob) -> None:
        await asyncio.to_thread(
            self._celery_app.send_task,
            WORKFLOW_EXECUTION_TASK,
            kwargs={"run_id": str(job.run_id)},
        )
