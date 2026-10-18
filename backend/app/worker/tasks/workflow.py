"""Celery task bridge for durable background workflow execution."""

import asyncio
import logging
from typing import Any
from uuid import UUID

from celery import shared_task

from app.composition.workflow_worker import open_workflow_worker
from app.integrations.celery.workflow_dispatcher import WORKFLOW_EXECUTION_TASK
from app.services.workflow import WorkflowExecutionJob

logger = logging.getLogger(__name__)


async def execute_workflow_job(run_id: str, *, task_id: str | None) -> dict[str, Any]:
    """Validate one broker payload, compose a runtime, and execute the run."""
    parsed_run_id = UUID(run_id)
    logger.info("workflow_task_started", extra={"run_id": run_id, "task_id": task_id})
    try:
        async with open_workflow_worker() as executor:
            result = await executor.execute(WorkflowExecutionJob(parsed_run_id))
    except Exception as error:
        logger.exception(
            "workflow_task_failed",
            extra={
                "run_id": run_id,
                "task_id": task_id,
                "exception_type": type(error).__name__,
            },
        )
        raise
    payload = {
        "run_id": str(result.run_id),
        "status": result.status.value,
        "lease_released": result.lease_released,
    }
    logger.info(
        "workflow_task_finished",
        extra={"run_id": run_id, "task_id": task_id, "status": result.status.value},
    )
    return payload


@shared_task(bind=True, name=WORKFLOW_EXECUTION_TASK)
def execute_workflow(self: Any, run_id: str) -> dict[str, Any]:
    """Bridge Celery's synchronous task contract to the async worker runtime."""
    return asyncio.run(execute_workflow_job(run_id, task_id=self.request.id))
