"""Tests for framework-agnostic agent execution contracts."""

from typing import Any

import pytest

from app.services.agent_runtime import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentRuntimeError,
)


def test_execution_request_preserves_fields() -> None:
    payload: dict[str, Any] = {"prompt": "Summarize this report."}
    request = AgentExecutionRequest(
        instruction="Provide a concise summary.",
        input=payload,
        model="gpt-test",
        metadata={"source": "workflow"},
    )

    assert request.instruction == "Provide a concise summary."
    assert request.input is payload
    assert request.model == "gpt-test"
    assert request.metadata == {"source": "workflow"}


def test_execution_request_metadata_is_a_read_only_shallow_snapshot() -> None:
    metadata = {"source": "workflow"}
    request = AgentExecutionRequest(instruction="Run", input=None, metadata=metadata)

    metadata["source"] = "changed"

    assert request.metadata["source"] == "workflow"
    with pytest.raises(TypeError):
        request.metadata["source"] = "runner"  # type: ignore[index]


def test_execution_result_preserves_output_and_read_only_metadata_snapshot() -> None:
    metadata = {"provider": "native"}
    result = AgentExecutionResult(output={"answer": 42}, metadata=metadata)

    metadata["provider"] = "changed"

    assert result.output == {"answer": 42}
    assert result.metadata["provider"] == "native"
    with pytest.raises(TypeError):
        result.metadata["provider"] = "other"  # type: ignore[index]


def test_runtime_error_preserves_properties_and_message() -> None:
    error = AgentRuntimeError("provider_unavailable", "Provider is unavailable.", retryable=True)

    assert error.code == "provider_unavailable"
    assert error.message == "Provider is unavailable."
    assert error.retryable is True
    assert str(error) == "Provider is unavailable."
