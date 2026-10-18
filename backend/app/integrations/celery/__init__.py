"""Celery integration adapters."""

from app.integrations.celery.workflow_dispatcher import CeleryWorkflowDispatcher

__all__ = ["CeleryWorkflowDispatcher"]
