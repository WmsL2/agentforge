"""Static contract for the additive execution claim/lease migration."""

import runpy
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID

MIGRATION = (
    Path(__file__).parents[4] / "alembic/versions/0041_add_workflow_execution_claim_lease.py"
)


def test_execution_claim_revision_chain():
    namespace = runpy.run_path(str(MIGRATION))
    assert namespace["revision"] == "0041_add_workflow_execution_claim_lease"
    assert namespace["down_revision"] == "0040_harden_workflow_workspace_scope"


def test_execution_claim_upgrade_and_downgrade_structure():
    namespace = runpy.run_path(str(MIGRATION))
    with (
        patch.object(namespace["op"], "add_column") as add,
        patch.object(namespace["op"], "create_check_constraint") as create,
    ):
        namespace["upgrade"]()
    assert all(call.args[0] == "workflow_runs" for call in add.call_args_list)
    columns = {call.args[1].name: call.args[1] for call in add.call_args_list}
    assert set(columns) == {
        "execution_claim_token",
        "execution_lease_expires_at",
        "execution_claim_generation",
    }
    assert isinstance(columns["execution_claim_token"].type, UUID)
    assert columns["execution_claim_token"].nullable
    assert isinstance(columns["execution_lease_expires_at"].type, DateTime)
    assert columns["execution_lease_expires_at"].type.timezone
    assert columns["execution_lease_expires_at"].nullable
    generation = columns["execution_claim_generation"]
    assert isinstance(generation.type, Integer) and not generation.nullable
    assert str(generation.server_default.arg) == "0"
    assert [call.args for call in create.call_args_list] == [
        (
            "execution_claim_generation_nonnegative",
            "workflow_runs",
            "execution_claim_generation >= 0",
        ),
        (
            "execution_claim_lease_pair",
            "workflow_runs",
            "(execution_claim_token IS NULL) = (execution_lease_expires_at IS NULL)",
        ),
    ]
    with (
        patch.object(namespace["op"], "drop_constraint") as drop_constraint,
        patch.object(namespace["op"], "drop_column") as drop,
    ):
        namespace["downgrade"]()
    assert [call.args[0] for call in drop_constraint.call_args_list] == [
        "execution_claim_lease_pair",
        "execution_claim_generation_nonnegative",
    ]
    assert all(call.kwargs == {"type_": "check"} for call in drop_constraint.call_args_list)
    assert [call.args for call in drop.call_args_list] == [
        ("workflow_runs", "execution_claim_generation"),
        ("workflow_runs", "execution_lease_expires_at"),
        ("workflow_runs", "execution_claim_token"),
    ]
