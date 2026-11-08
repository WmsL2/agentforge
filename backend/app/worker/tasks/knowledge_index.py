"""Celery bridges for durable knowledge indexing and recovery."""

import asyncio
from typing import Any
from uuid import UUID

from celery import shared_task

from app.composition.knowledge_index_recovery import open_knowledge_index_recovery_scanner
from app.composition.knowledge_index_worker import open_knowledge_index_worker
from app.integrations.celery.knowledge_index_dispatcher import KNOWLEDGE_INDEX_TASK

KNOWLEDGE_INDEX_RECOVERY_TASK = "agentforge.knowledge.index.recovery.scan"


async def execute_knowledge_index_job(job_id: str) -> dict[str, str]:
    parsed_job_id = UUID(job_id)
    async with open_knowledge_index_worker() as executor:
        result = await executor.execute(parsed_job_id)
    return {"job_id": str(result.job_id), "status": result.status}


@shared_task(name=KNOWLEDGE_INDEX_TASK)
def execute_knowledge_index(job_id: str) -> dict[str, str]:
    return asyncio.run(execute_knowledge_index_job(job_id))


async def scan_knowledge_index_recovery() -> dict[str, int]:
    async with open_knowledge_index_recovery_scanner() as scanner:
        result = await scanner.scan_once()
    return {
        "scanned": result.scanned,
        "dispatched": result.dispatched,
        "failed": result.failed,
    }


@shared_task(name=KNOWLEDGE_INDEX_RECOVERY_TASK)
def scan_knowledge_indexes() -> dict[str, Any]:
    return asyncio.run(scan_knowledge_index_recovery())
