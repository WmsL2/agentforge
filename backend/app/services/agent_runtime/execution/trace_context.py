"""Task-local trace identity propagated from an agent run to adapted tools."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AgentTraceContext:
    run_id: UUID | None
    step_id: UUID | None


_trace_context: ContextVar[AgentTraceContext | None] = ContextVar("agent_trace_context", default=None)


@contextmanager
def bind_trace_context(run_id: UUID | None, step_id: UUID | None) -> Iterator[None]:
    """Bind trace identity only for one agent-run task and always reset it."""
    token: Token[AgentTraceContext | None] = _trace_context.set(
        AgentTraceContext(run_id=run_id, step_id=step_id)
    )
    try:
        yield
    finally:
        _trace_context.reset(token)


def current_trace_context() -> AgentTraceContext | None:
    """Return this task's bound trace identity, if the caller has one."""
    return _trace_context.get()
