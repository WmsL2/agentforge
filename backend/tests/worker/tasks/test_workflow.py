"""Celery workflow task bridge tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.workflow import (
    BackgroundRunExecutionResult,
    BackgroundRunExecutionStatus,
)
from app.worker.tasks import workflow


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "released"),
    [
        (BackgroundRunExecutionStatus.COMPLETED, True),
        (BackgroundRunExecutionStatus.PAUSED, True),
        (BackgroundRunExecutionStatus.FAILED, True),
        (BackgroundRunExecutionStatus.NOT_CLAIMED, False),
        (BackgroundRunExecutionStatus.LEASE_LOST, False),
    ],
)
async def test_async_entry_returns_json_safe_result(
    monkeypatch: pytest.MonkeyPatch,
    status: BackgroundRunExecutionStatus,
    released: bool,
) -> None:
    run_id = uuid4()
    executor = AsyncMock()
    executor.execute.return_value = BackgroundRunExecutionResult(run_id, status, released)

    @asynccontextmanager
    async def fake_runtime() -> AsyncIterator[AsyncMock]:
        yield executor

    monkeypatch.setattr(workflow, "open_workflow_worker", fake_runtime)

    result = await workflow.execute_workflow_job(str(run_id), task_id="task-1")

    assert result == {
        "run_id": str(run_id),
        "status": status.value,
        "lease_released": released,
    }
    assert executor.execute.await_args.args[0].run_id == run_id


@pytest.mark.anyio
async def test_async_entry_rejects_an_invalid_uuid_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = MagicRuntime()
    monkeypatch.setattr(workflow, "open_workflow_worker", runtime)

    with pytest.raises(ValueError):
        await workflow.execute_workflow_job("not-a-uuid", task_id="task-1")

    assert not runtime.entered


@pytest.mark.anyio
async def test_async_entry_propagates_infrastructure_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    executor = AsyncMock()
    executor.execute.side_effect = ConnectionError("database unavailable")

    @asynccontextmanager
    async def fake_runtime() -> AsyncIterator[AsyncMock]:
        yield executor

    monkeypatch.setattr(workflow, "open_workflow_worker", fake_runtime)

    with pytest.raises(ConnectionError, match="database unavailable"):
        await workflow.execute_workflow_job(str(run_id), task_id="task-1")


def test_synchronous_task_bridge_uses_async_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = str(uuid4())
    expected = {"run_id": run_id, "status": "completed", "lease_released": True}
    entry = AsyncMock(return_value=expected)
    monkeypatch.setattr(workflow, "execute_workflow_job", entry)

    assert workflow.execute_workflow.run(run_id) == expected
    entry.assert_awaited_once()
    assert entry.await_args.args == (run_id,)


class MagicRuntime:
    entered = False

    async def __aenter__(self):
        self.entered = True
        raise AssertionError("runtime should not be entered")

    async def __aexit__(self, *args):
        return None
