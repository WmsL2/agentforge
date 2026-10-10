"""PostgreSQL statement and repository transaction boundary tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.repositories.workflow.run import claim as repository
from app.services.workflow.application.background.domain import WorkflowExecutionLease


def lease_row():
    return {
        "run_id": uuid4(),
        "claim_token": uuid4(),
        "generation": 3,
        "expires_at": datetime(2030, 1, 1, tzinfo=UTC),
    }


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["claim", "renew", "release"])
@pytest.mark.parametrize("found", [True, False])
async def test_conditional_updates_return_database_values_without_committing(operation, found):
    db = AsyncMock()
    result = MagicMock()
    db.execute.return_value = result
    row = lease_row()
    value = WorkflowExecutionLease(**row)
    result.mappings.return_value.one_or_none.return_value = row if found else None
    result.scalar_one_or_none.return_value = value.run_id if found else None
    duration = timedelta(seconds=30)
    args = (
        (value.run_id, duration)
        if operation == "claim"
        else ((value, duration) if operation == "renew" else (value,))
    )
    returned = await getattr(repository, f"{operation}_execution")(db, *args)
    assert returned == (found if operation == "release" else (value if found else None))
    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert sql.startswith("UPDATE workflow_runs SET")
    assert "RETURNING" in sql and "clock_timestamp()" in sql
    assert "status=" not in sql.split(" WHERE ")[0]
    if operation == "claim":
        assert "execution_claim_generation +" in sql
        assert "execution_claim_token IS NOT NULL" in sql
        assert "execution_lease_expires_at <= clock_timestamp()" in sql
        assert "pending" in compiled.params.values()
        assert "running" in compiled.params.values()
        assert compiled.params["execution_claim_token"] != value.claim_token
    else:
        assert "execution_claim_token =" in sql.split(" WHERE ")[1]
        assert "execution_claim_generation =" in sql.split(" WHERE ")[1]
        assert "execution_lease_expires_at > clock_timestamp()" in sql
    if operation == "release":
        assert "execution_claim_generation=" not in sql.split(" WHERE ")[0]
        assert compiled.params["execution_claim_token"] is None
        assert compiled.params["execution_lease_expires_at"] is None
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("exists,valid", [(True, True), (True, False), (False, False)])
async def test_fencing_locks_before_checking_credentials_and_clock(exists, valid):
    db = AsyncMock()
    value = WorkflowExecutionLease(**lease_row())
    db.scalar.side_effect = [value.run_id if exists else None, value.run_id if valid else None]
    assert await repository.lock_and_validate_execution_lease(db, value) is valid
    calls = db.scalar.await_args_list
    first = str(calls[0].args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in first
    assert "clock_timestamp()" not in first
    if exists:
        second = str(calls[1].args[0].compile(dialect=postgresql.dialect()))
        assert "execution_claim_token =" in second
        assert "execution_claim_generation =" in second
        assert "execution_lease_expires_at > clock_timestamp()" in second
    else:
        assert len(calls) == 1
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()
