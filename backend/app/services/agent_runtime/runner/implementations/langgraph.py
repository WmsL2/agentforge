"""Stateless LangGraph implementation of the Agent Runtime SPI."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict

from app.core.config import settings
from app.services.agent_runtime.execution.domain import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentRuntimeError,
)


class _BoundAsyncChatModel(Protocol):
    """The minimal model capability needed by the LangGraph model node."""

    async def ainvoke(self, input: list[BaseMessage]) -> AIMessage:
        """Return one model response for the supplied messages."""


class _AsyncChatModel(_BoundAsyncChatModel, Protocol):
    """A chat model that can bind LangChain tools before invocation."""

    def bind_tools(self, tools: Sequence[BaseTool]) -> _BoundAsyncChatModel:
        """Return a chat model configured with the supplied tools."""


class _LangGraphAgentState(TypedDict):
    """The isolated state of one LangGraph Agent Runtime execution."""

    messages: Annotated[list[BaseMessage], add_messages]
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

    def __init__(
        self,
        model_factory: ModelFactory | None = None,
        tools: Sequence[BaseTool] | None = None,
    ) -> None:
        self._model_factory = model_factory or self._create_model
        self._tools = tuple(tools or ())
        self._graph = self._build_graph()

    @staticmethod
    def _create_model(model_name: str) -> _AsyncChatModel:
        return ChatOpenAI(
            model=model_name,
            temperature=settings.AI_TEMPERATURE,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL or None,
        )

    async def _model_node(self, state: _LangGraphAgentState) -> dict[str, Any]:
        model = self._model_factory(state["model_name"])
        if self._tools:
            model = model.bind_tools(self._tools)
        response = await model.ainvoke(state["messages"])
        return {"messages": [response], "output": response.content}

    def _build_graph(self):
        graph = StateGraph(_LangGraphAgentState)  # ty: ignore[invalid-argument-type]
        graph.add_node("model", self._model_node)
        graph.add_edge(START, "model")
        if self._tools:
            graph.add_node("tools", ToolNode(self._tools, handle_tool_errors=False))
            graph.add_conditional_edges(
                "model",
                tools_condition,
                {"tools": "tools", "__end__": END},
            )
            graph.add_edge("tools", "model")
        else:
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
