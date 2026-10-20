"""Celery Beat bridge for bounded durable-workflow recovery scans."""

import asyncio
from typing import Any

from celery import shared_task

from app.composition.workflow_recovery import open_workflow_recovery_scanner

WORKFLOW_RECOVERY_SCAN_TASK = "agentforge.workflow.recovery.scan"


async def scan_workflow_recovery() -> dict[str, int]:
    async with open_workflow_recovery_scanner() as scanner:
        result = await scanner.scan_once()
    return {
        "scanned": result.scanned,
        "dispatched": result.dispatched,
        "skipped": result.skipped,
        "failed": result.failed,
    }


@shared_task(name=WORKFLOW_RECOVERY_SCAN_TASK)
def scan_recovery() -> dict[str, Any]:
    return asyncio.run(scan_workflow_recovery())
