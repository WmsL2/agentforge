"""Async workflow-run dependency composition tests."""

from unittest.mock import MagicMock

from app.api.deps import (
    get_workflow_async_run_service,
    get_workflow_execution_dispatcher,
)
from app.integrations.celery import CeleryWorkflowDispatcher
from app.services.workflow import WorkflowAsyncRunService
from app.worker.celery_app import celery_app


def test_production_dispatcher_dependency_uses_celery_adapter() -> None:
    dispatcher = get_workflow_execution_dispatcher()
    assert isinstance(dispatcher, CeleryWorkflowDispatcher)
    assert dispatcher._celery_app is celery_app


def test_async_service_dependency_uses_injected_dispatcher() -> None:
    db, workflow_service, dispatcher = MagicMock(), MagicMock(), MagicMock()
    service = get_workflow_async_run_service(db, workflow_service, dispatcher)
    assert isinstance(service, WorkflowAsyncRunService)
    assert service._db is db
    assert service._workflow_service is workflow_service
    assert service._dispatcher is dispatcher
