"""Stateless LangGraph implementation of the Agent Runtime SPI."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.core.config import settings
from app.services.agent_runtime.execution.domain import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentRuntimeError,
)


class _AsyncChatModel(Protocol):
    """The minimal model capability needed by the LangGraph model node."""

    async def ainvoke(self, input: list[BaseMessage]) -> AIMessage:
        """Return one model response for the supplied messages."""


class _LangGraphAgentState(TypedDict):
    """The isolated state of one LangGraph Agent Runtime execution."""

    messages: list[BaseMessage]
    model_name: str
    output: Any


ModelFactory = Callable[[str], _AsyncChatModel]


def _render_input(value: Any) -> str:
    """Render generic runtime input without rejecting non-JSON values."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError, RecursionError):
        return str(value)


class LangGraphAgentRunner:
    """Run a stateless single-model LangGraph execution for one request."""

    def __init__(self, model_factory: ModelFactory | None = None) -> None:
        self._model_factory = model_factory or self._create_model
        self._graph = self._build_graph()

    @staticmethod
    def _create_model(model_name: str) -> _AsyncChatModel:
        return ChatOpenAI(
            model=model_name,
            temperature=settings.AI_TEMPERATURE,
            api_key=settings.OPENAI_API_KEY,
        )

    async def _model_node(self, state: _LangGraphAgentState) -> dict[str, Any]:
        model = self._model_factory(state["model_name"])
        response = await model.ainvoke(state["messages"])
        return {"output": response.content}

    def _build_graph(self):
        graph = StateGraph(_LangGraphAgentState)  # ty: ignore[invalid-argument-type]
        graph.add_node("model", self._model_node)
        graph.add_edge(START, "model")
        graph.add_edge("model", END)
        return graph.compile()

    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Run one independent Agent Runtime request through LangGraph."""
        effective_model = request.model if request.model is not None else settings.AI_MODEL
        messages: list[BaseMessage] = [
            SystemMessage(content=request.instruction),
            HumanMessage(content=_render_input(request.input)),
        ]
        try:
            result = await self._graph.ainvoke(
                {"messages": messages, "model_name": effective_model}
            )
        except Exception as exception:
            raise AgentRuntimeError(
                code="langgraph_execution_failed",
                message=str(exception) or type(exception).__name__,
            ) from exception
        return AgentExecutionResult(output=result["output"])
