"""Celery worker task-registration tests."""

from app.worker.celery_app import celery_app


def test_worker_loader_registers_smoke_and_workflow_tasks() -> None:
    celery_app.loader.import_default_modules()

    assert "agentforge.smoke.echo" in celery_app.tasks
    assert "agentforge.workflow.execute" in celery_app.tasks
