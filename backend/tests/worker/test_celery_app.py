"""Celery worker task-registration tests."""

from celery import Celery

from app.core.config import Settings, settings
from app.worker.celery_app import celery_app


def test_worker_loader_registers_smoke_and_workflow_tasks() -> None:
    celery_app.loader.import_default_modules()

    assert "agentforge.smoke.echo" in celery_app.tasks
    assert "agentforge.workflow.execute" in celery_app.tasks


def test_existing_celery_contract_and_both_recovery_schedules():
    assert celery_app.conf.broker_url == settings.CELERY_BROKER_URL
    assert celery_app.conf.result_backend == settings.CELERY_RESULT_BACKEND
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.result_expires == 3600
    assert celery_app.conf.beat_schedule["workflow-recovery-scan"]["task"] == (
        "agentforge.workflow.recovery.scan"
    )
    assert celery_app.conf.beat_schedule["knowledge-index-recovery-scan"]["task"] == (
        "agentforge.knowledge.index.recovery.scan"
    )
    celery_app.loader.import_default_modules()
    assert "agentforge.knowledge.index.execute" in celery_app.tasks
    assert "agentforge.knowledge.index.recovery.scan" in celery_app.tasks


def test_real_celery_broker_and_result_backend_parsers_without_connecting():
    password = " @:/#%?雪%40 end "
    config = Settings(
        _env_file=None, REDIS_HOST="::1", REDIS_PASSWORD=password, REDIS_PORT=6380, REDIS_DB=15
    )
    client = Celery(
        "offline-url-proof",
        broker=config.CELERY_BROKER_URL,
        backend=config.CELERY_RESULT_BACKEND,
        set_as_current=False,
    )
    try:
        connection = client.connection_for_write()
        assert connection.hostname == "::1"
        assert connection.password == password
        assert connection.port == 6380
        assert connection.virtual_host == "15"
        backend = client.backend
        assert backend.connparams["password"] == password
        assert backend.connparams["host"] == "::1"
        assert backend.connparams["port"] == 6380
        assert backend.connparams["db"] == 15
    finally:
        client.close()
