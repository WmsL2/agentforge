"""Celery workflow dispatcher contract tests."""

import asyncio
import threading
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.integrations.celery.workflow_dispatcher import (
    WORKFLOW_EXECUTION_TASK,
    CeleryWorkflowDispatcher,
)
from app.services.workflow import WorkflowExecutionJob


@pytest.mark.anyio
async def test_dispatch_publishes_only_the_string_run_id() -> None:
    publisher = MagicMock()
    run_id = uuid4()

    result = await CeleryWorkflowDispatcher(publisher).dispatch(WorkflowExecutionJob(run_id))

    assert result is None
    publisher.send_task.assert_called_once_with(
        WORKFLOW_EXECUTION_TASK,
        kwargs={"run_id": str(run_id)},
    )


@pytest.mark.anyio
async def test_dispatch_propagates_publish_errors() -> None:
    publisher = MagicMock()
    publisher.send_task.side_effect = ConnectionError("broker unavailable")

    with pytest.raises(ConnectionError, match="broker unavailable"):
        await CeleryWorkflowDispatcher(publisher).dispatch(WorkflowExecutionJob(uuid4()))


@pytest.mark.anyio
async def test_dispatch_does_not_block_the_event_loop() -> None:
    entered = threading.Event()
    release = threading.Event()
    publisher = MagicMock()

    def blocking_publish(*args, **kwargs) -> None:
        entered.set()
        assert release.wait(timeout=2)

    publisher.send_task.side_effect = blocking_publish
    dispatch = asyncio.create_task(
        CeleryWorkflowDispatcher(publisher).dispatch(WorkflowExecutionJob(uuid4()))
    )
    assert await asyncio.to_thread(entered.wait, 1)
    await asyncio.sleep(0)
    assert not dispatch.done()
    release.set()
    await dispatch
