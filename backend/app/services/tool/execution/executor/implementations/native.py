"""Native Python callable implementation of the ToolExecutor protocol."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from app.services.tool.execution.domain import ToolExecutionRequest, ToolExecutionResult


class NativeCallableToolExecutor:
    """Adapt a sync or async Python callable to the ToolExecutor protocol."""

    def __init__(self, callable_: Callable[..., Any]) -> None:
        """Store a callable to invoke with each request's keyword arguments."""
        if not callable(callable_):
            raise TypeError("callable_ must be callable")
        self._callable = callable_

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """Invoke the callable with request arguments and preserve its output."""
        arguments = dict(request.arguments)
        if inspect.iscoroutinefunction(self._callable):
            output = self._callable(**arguments)
        else:
            output = await asyncio.to_thread(self._callable, **arguments)

        if inspect.isawaitable(output):
            output = await output

        return ToolExecutionResult(output=output)
