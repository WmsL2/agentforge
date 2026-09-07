"""Offline tests for the stateless LangGraph Agent Runtime runner."""

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

import app.services.agent_runtime as agent_runtime
from app.core.config import settings
from app.services.agent_runtime import (
    AgentExecutionRequest,
    AgentRuntimeError,
)
from app.services.agent_runtime.runner.implementations import LangGraphAgentRunner
from app.services.agent_runtime.runner.implementations import langgraph as langgraph_module


class FakeChatModel:
    def __init__(self, response: AIMessage | None = None, error: Exception | None = None) -> None:
        self.calls: list[list[BaseMessage]] = []
        self._response = response or AIMessage(content="answer")
        self._error = error

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.calls.append(messages)
        if self._error is not None:
            raise self._error
        return self._response


class RecordingModelFactory:
    def __init__(self, model: FakeChatModel) -> None:
        self.models: list[str] = []
        self._model = model

    def __call__(self, model_name: str) -> FakeChatModel:
        self.models.append(model_name)
        return self._model


def test_public_runtime_exports_remain_contract_only() -> None:
    """The top-level package must not expose concrete framework runners."""
    assert agent_runtime.__all__ == [
        "AgentExecutionRequest",
        "AgentExecutionResult",
        "AgentRunner",
        "AgentRuntimeError",
    ]


def test_default_model_factory_uses_generic_openai_compatible_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_chat_openai(**kwargs: object) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(langgraph_module, "ChatOpenAI", fake_chat_openai)
    monkeypatch.setattr(settings, "AI_TEMPERATURE", 0.25)
    monkeypatch.setattr(settings, "LLM_API_KEY", "runtime-key")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://compatible.example/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "legacy-template-key")

    model = LangGraphAgentRunner._create_model("compatible-model")

    assert model is sentinel
    assert captured == {
        "model": "compatible-model",
        "temperature": 0.25,
        "api_key": "runtime-key",
        "base_url": "https://compatible.example/v1",
    }


def run_request(
    runner: LangGraphAgentRunner,
    *,
    instruction: str = "Follow the instruction.",
    input: Any = "hello",
    model: str | None = None,
):
    return asyncio.run(
        runner.run(AgentExecutionRequest(instruction=instruction, input=input, model=model))
    )


def test_langgraph_runner_maps_instruction_string_input_and_output() -> None:
    model = FakeChatModel(AIMessage(content="answer"))
    factory = RecordingModelFactory(model)
    result = run_request(
        LangGraphAgentRunner(model_factory=factory),
        instruction="Answer concisely.",
        input="hello",
        model="override-model",
    )

    assert factory.models == ["override-model"]
    assert isinstance(model.calls[0][0], SystemMessage)
    assert model.calls[0][0].content == "Answer concisely."
    assert isinstance(model.calls[0][1], HumanMessage)
    assert model.calls[0][1].content == "hello"
    assert result.output == "answer"
    assert result.metadata == {}


@pytest.mark.parametrize(
    ("input", "rendered"), [({"a": 1}, '{"a": 1}'), ([1, 2], "[1, 2]"), (42, "42")]
)
def test_langgraph_runner_renders_json_compatible_input(input: Any, rendered: str) -> None:
    model = FakeChatModel()
    runner = LangGraphAgentRunner(model_factory=RecordingModelFactory(model))

    run_request(runner, input=input)

    assert model.calls[0][1].content == rendered


def test_langgraph_runner_falls_back_to_string_for_non_json_input() -> None:
    class NonJsonValue:
        def __str__(self) -> str:
            return "non-json-value"

    model = FakeChatModel()
    runner = LangGraphAgentRunner(model_factory=RecordingModelFactory(model))

    run_request(runner, input=NonJsonValue())

    assert model.calls[0][1].content == "non-json-value"


def test_langgraph_runner_uses_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AI_MODEL", "configured-default")
    model = FakeChatModel()
    factory = RecordingModelFactory(model)

    run_request(LangGraphAgentRunner(model_factory=factory))

    assert factory.models == ["configured-default"]


def test_langgraph_runner_preserves_structured_message_content() -> None:
    structured_content: list[dict[str, str]] = [{"type": "text", "text": "answer"}]
    model = FakeChatModel(AIMessage(content=structured_content))

    result = run_request(LangGraphAgentRunner(model_factory=RecordingModelFactory(model)))

    assert result.output == structured_content
    assert not isinstance(result.output, str)


def test_langgraph_runner_translates_model_errors() -> None:
    original = RuntimeError("provider exploded")
    model = FakeChatModel(error=original)

    with pytest.raises(AgentRuntimeError) as error:
        run_request(LangGraphAgentRunner(model_factory=RecordingModelFactory(model)))

    assert error.value.code == "langgraph_execution_failed"
    assert error.value.message == "provider exploded"
    assert error.value.retryable is False
    assert error.value.__cause__ is original


def test_langgraph_runner_does_not_retain_messages_between_runs() -> None:
    model = FakeChatModel()
    runner = LangGraphAgentRunner(model_factory=RecordingModelFactory(model))

    run_request(runner, instruction="First instruction.", input="first input")
    run_request(runner, instruction="Second instruction.", input="second input")

    assert len(model.calls) == 2
    assert [message.content for message in model.calls[0]] == ["First instruction.", "first input"]
    assert [message.content for message in model.calls[1]] == [
        "Second instruction.",
        "second input",
    ]
