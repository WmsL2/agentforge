"""Celery adapter for durable knowledge index job IDs."""

from uuid import UUID

from celery import Celery

KNOWLEDGE_INDEX_TASK = "agentforge.knowledge.index.execute"


class CeleryKnowledgeIndexDispatcher:
    def __init__(self, celery_app: Celery) -> None:
        self._celery_app = celery_app

    async def dispatch(self, job_id: UUID) -> None:
        self._celery_app.send_task(KNOWLEDGE_INDEX_TASK, args=[str(job_id)])
