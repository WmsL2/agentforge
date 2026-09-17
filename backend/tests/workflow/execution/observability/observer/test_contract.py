"""Tests for framework-independent workflow observation contracts."""

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from app.services.workflow import (
    NodeExecutionContext,
    NodeExecutionResult,
    RunStepError,
    TraceEventKind,
    WorkflowExecutionObserver,
    WorkflowNode,
    WorkflowObservationContext,
)


class FakeObserver:
    async def start_step(
        self,
        *,
        run_id: object,
        node: WorkflowNode,
        execution_context: NodeExecutionContext,
    ) -> WorkflowObservationContext:
        return WorkflowObservationContext(run_id=run_id)  # type: ignore[arg-type]

    async def complete_step(
        self, context: WorkflowObservationContext, *, result: NodeExecutionResult
    ) -> None:
        return None

    async def fail_step(
        self,
        context: WorkflowObservationContext,
        *,
        error: RunStepError,
        metadata: dict[str, object],
    ) -> None:
        return None

    async def interrupt_step(
        self, context: WorkflowObservationContext, *, result: NodeExecutionResult
    ) -> None:
        return None

    async def record_event(
        self,
        context: WorkflowObservationContext,
        *,
        kind: TraceEventKind,
        payload: dict[str, object],
    ) -> None:
        return None


def _accepts_observer(observer: WorkflowExecutionObserver) -> WorkflowExecutionObserver:
    return observer


def test_observation_context_preserves_run_and_optional_step_identity() -> None:
    run_id = uuid4()
    step_id = uuid4()

    assert WorkflowObservationContext(run_id=run_id, step_id=step_id) == WorkflowObservationContext(
        run_id=run_id,
        step_id=step_id,
    )
    assert WorkflowObservationContext(run_id=run_id).step_id is None


def test_observation_context_is_frozen() -> None:
    context = WorkflowObservationContext(run_id=uuid4())

    with pytest.raises(FrozenInstanceError):
        context.step_id = uuid4()  # type: ignore[misc]


def test_structurally_compatible_fake_satisfies_observer_static_contract() -> None:
    observer: WorkflowExecutionObserver = FakeObserver()

    assert _accepts_observer(observer) is observer
