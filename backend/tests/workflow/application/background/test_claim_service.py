"""Lease domain and application transaction ownership tests."""

import asyncio
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import workflow
from app.services.workflow.application import background
from app.services.workflow.application.background.claim_service import WorkflowExecutionClaimService
from app.services.workflow.application.background.domain import WorkflowExecutionLease


def lease() -> WorkflowExecutionLease:
    return WorkflowExecutionLease(uuid4(), uuid4(), 1, datetime(2030, 1, 1, tzinfo=UTC))


def test_lease_fields_types_and_immutability():
    value = lease()
    assert [field.name for field in fields(value)] == [
        "run_id",
        "claim_token",
        "generation",
        "expires_at",
    ]
    assert get_type_hints(WorkflowExecutionLease) == {
        "run_id": UUID,
        "claim_token": UUID,
        "generation": int,
        "expires_at": datetime,
    }
    assert value.expires_at.utcoffset() == timedelta(0)
    with pytest.raises(FrozenInstanceError):
        value.generation = 2


def test_new_types_are_publicly_exported():
    from app.services.workflow import application

    for module in (workflow, application, background):
        assert module.WorkflowExecutionClaimService is WorkflowExecutionClaimService
        assert module.WorkflowExecutionLease is WorkflowExecutionLease
        assert "WorkflowExecutionClaimService" in module.__all__
        assert "WorkflowExecutionLease" in module.__all__


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operation,success",
    [
        ("claim", True),
        ("claim", False),
        ("renew", True),
        ("renew", False),
        ("release", True),
        ("release", False),
    ],
)
async def test_operations_use_short_application_owned_transactions(operation, success):
    db = MagicMock(spec=AsyncSession)
    transaction = db.begin.return_value
    value = lease()
    duration = timedelta(minutes=1)
    updated = replace(value, expires_at=value.expires_at + duration)
    expected = success if operation == "release" else (updated if success else None)
    args = (
        (value.run_id, duration)
        if operation == "claim"
        else ((value, duration) if operation == "renew" else (value,))
    )
    with patch(
        f"app.services.workflow.application.background.claim_service.claim_repo.{operation}_execution",
        new_callable=AsyncMock,
        return_value=expected,
    ) as repository:
        result = await getattr(WorkflowExecutionClaimService(db), operation)(*args)
    assert result == expected
    repository.assert_awaited_once_with(db, *args)
    db.begin.assert_called_once_with()
    transaction.__aenter__.assert_awaited_once()
    transaction.__aexit__.assert_awaited_once_with(None, None, None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "duration", [timedelta(0), timedelta(seconds=-1), None, 1, float("inf"), float("nan")]
)
@pytest.mark.parametrize("operation", ["claim", "renew"])
async def test_invalid_duration_is_rejected_before_starting_transaction(operation, duration):
    db = MagicMock(spec=AsyncSession)
    value = lease()
    subject = value.run_id if operation == "claim" else value
    with pytest.raises(ValueError, match="strictly positive timedelta"):
        await getattr(WorkflowExecutionClaimService(db), operation)(subject, duration)
    db.begin.assert_not_called()
    db.execute.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["claim", "renew", "release"])
@pytest.mark.parametrize("exception_type", [RuntimeError, asyncio.CancelledError])
async def test_errors_and_cancellation_reach_transaction_rollback(operation, exception_type):
    db = MagicMock(spec=AsyncSession)
    db.begin.return_value.__aexit__.return_value = False
    value = lease()
    args = (
        (value.run_id, timedelta(seconds=30))
        if operation == "claim"
        else ((value, timedelta(seconds=30)) if operation == "renew" else (value,))
    )
    error = exception_type("interrupted")
    with (
        patch(
            f"app.services.workflow.application.background.claim_service.claim_repo.{operation}_execution",
            new_callable=AsyncMock,
            side_effect=error,
        ),
        pytest.raises(exception_type),
    ):
        await getattr(WorkflowExecutionClaimService(db), operation)(*args)
    exit_args = db.begin.return_value.__aexit__.await_args.args
    assert exit_args[0] is exception_type
    assert exit_args[1] is error
