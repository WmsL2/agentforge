from datetime import timedelta
from uuid import uuid4

import pytest

from app.services.workflow.application.background.recovery_scanner import WorkflowRecoveryScanner
from app.worker.celery_app import WORKFLOW_RECOVERY_SCAN_TASK, celery_app


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def begin(self):
        return self


class Dispatcher:
    def __init__(self, failing=None):
        self.jobs = []
        self.failing = failing

    async def dispatch(self, job):
        self.jobs.append(job)
        if job.run_id == self.failing:
            raise ConnectionError("broker unavailable")


@pytest.mark.anyio
async def test_scan_locks_candidates_then_continues_after_one_publish_failure(monkeypatch):
    first, second = uuid4(), uuid4()

    async def candidates(db, *, limit, redispatch_delay):
        assert limit == 2
        assert redispatch_delay == timedelta(seconds=60)
        return [first, second]

    monkeypatch.setattr(
        "app.services.workflow.application.background.recovery_scanner.run_repo.list_recoverable_workflow_run_ids_for_update",
        candidates,
    )
    dispatcher = Dispatcher(failing=first)
    scanner = WorkflowRecoveryScanner(
        lambda: Session(), dispatcher, batch_size=2, redispatch_delay=timedelta(seconds=60)
    )

    result = await scanner.scan_once()

    assert [job.run_id for job in dispatcher.jobs] == [first, second]
    assert result.scanned == 2
    assert result.dispatched == 1
    assert result.failed == 1
    assert result.skipped == 0


@pytest.mark.parametrize("batch_size", [0, -1, True, "100"])
def test_scan_requires_positive_integer_batch_size(batch_size):
    with pytest.raises(ValueError):
        WorkflowRecoveryScanner(
            lambda: Session(),
            Dispatcher(),
            batch_size=batch_size,
            redispatch_delay=timedelta(seconds=60),
        )


@pytest.mark.parametrize("delay", [timedelta(0), timedelta(seconds=-1), "60"])
def test_scan_requires_positive_redispatch_delay(delay):
    with pytest.raises(ValueError, match="redispatch_delay"):
        WorkflowRecoveryScanner(
            lambda: Session(), Dispatcher(), batch_size=1, redispatch_delay=delay
        )


def test_recovery_beat_schedule_targets_the_registered_task() -> None:
    schedule = celery_app.conf.beat_schedule["workflow-recovery-scan"]
    assert schedule["task"] == WORKFLOW_RECOVERY_SCAN_TASK
    assert "app.worker.tasks.recovery" in celery_app.conf.include
