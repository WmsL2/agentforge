"""Bounded knowledge recovery scanner tests."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.knowledge.index_recovery import KnowledgeIndexRecoveryScanner


class _Context:
    def __init__(self):
        self.session = SimpleNamespace(begin=lambda: self)

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        return False


@pytest.mark.anyio
async def test_scan_commits_selection_then_dispatches_each_job_and_isolates_failures() -> None:
    job_ids = [uuid4(), uuid4()]
    dispatcher = SimpleNamespace(dispatch=AsyncMock(side_effect=[None, RuntimeError("offline")]))
    scanner = KnowledgeIndexRecoveryScanner(
        lambda: _Context(),
        dispatcher,
        batch_size=10,
        redispatch_delay=timedelta(seconds=30),
    )
    with patch(
        "app.services.knowledge.index_recovery.index_repo.list_recoverable_job_ids",
        AsyncMock(return_value=job_ids),
    ) as listing:
        result = await scanner.scan_once()
    assert (result.scanned, result.dispatched, result.failed) == (2, 1, 1)
    assert dispatcher.dispatch.await_count == 2
    listing.assert_awaited_once()


def test_scanner_rejects_unbounded_configuration() -> None:
    dispatcher = SimpleNamespace(dispatch=AsyncMock())
    with pytest.raises(ValueError):
        KnowledgeIndexRecoveryScanner(
            lambda: _Context(),
            dispatcher,
            batch_size=0,
            redispatch_delay=timedelta(seconds=1),
        )
