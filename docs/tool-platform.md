# Tool Platform — v0.4

## Scope

v0.4 establishes a framework-independent AgentForge Tool Platform. It defines
what a tool is, validates its JSON Schema arguments, resolves registered tools,
and provides one uniform execution boundary. LangGraph is an integration
consumer of this platform, not its registry or executor implementation.

## Domain contracts

- `ToolDefinition` describes a tool: its name, description, JSON Schema input,
  and metadata.
- `ToolExecutionRequest` identifies one tool invocation and its arguments.
- `ToolExecutionResult` carries generic output and metadata.
- `ToolExecutionError` is the Tool Platform's uniform execution error boundary.

`ToolSchemaValidator` interprets schemas as JSON Schema Draft 2020-12.
`ToolExecutor` is the asynchronous execution SPI, and `ToolRegistration`
combines a definition with its executor.

## Execution architecture

```text
Caller
  | ToolExecutionRequest
  v
ToolExecutionService
  | registry.resolve(tool_name)
  v
ToolRegistry
  | ToolRegistration: definition + executor
  v
ToolSchemaValidator
  | validates arguments
  v
ToolExecutor
  | execute(request)
  v
ToolExecutionResult
```

`ToolRegistry` finds tools. `ToolSchemaValidator` checks arguments.
`ToolExecutor` runs one request. `ToolExecutionService` orchestrates resolve,
validate, execute, and error normalization without reconstructing the request.

## Native callable tools

`NativeCallableToolExecutor` adapts a Python callable. It supports synchronous
callables, asynchronous callables, and synchronous callables that return an
awaitable. Synchronous calls run through `asyncio.to_thread` so they do not
block the event loop.

## Production composition

`backend/app/api/deps.py` is the composition root. v0.4 registers one
production tool, `current_datetime`, sourced from
`app.agents.utils.get_current_datetime` and executed by
`NativeCallableToolExecutor`.

## LangGraph adapter and agent loop

`LangGraphToolAdapter.adapt()` converts a `ToolDefinition` into a
`StructuredTool`, retaining the definition's JSON Schema as the source of
truth:

```text
ToolDefinition -> LangGraphToolAdapter.adapt() -> StructuredTool
```

At execution time the adapter creates a `ToolExecutionRequest` and calls only
`ToolExecutionService`; it neither executes Python callables directly nor
accesses `ToolExecutor` directly.

`LangGraphAgentRunner` binds these structured tools and uses this graph for a
tool-enabled run:

```text
model
  | AIMessage
  v
tools_condition
  |-- no tool_calls --> END
  `-- tool_calls --> ToolNode --> ToolMessage --> model
```

Its state uses `add_messages`, retaining `SystemMessage`, `HumanMessage`,
`AIMessage(tool_call)`, `ToolMessage`, and subsequent AI messages for the
single run. This is state merging, not persistent memory.

## Failure boundary

`ToolNode(handle_tool_errors=False)` lets `ToolExecutionError` escape. The
outer `LangGraphAgentRunner.run()` boundary converts it to
`AgentRuntimeError(code="langgraph_execution_failed")`, preserving the original
tool error as the exception cause.

## Non-goals

v0.4 does not implement a Workflow TOOL Node, registry list/discover API,
dynamic discovery, per-agent tool binding, permissions, policy, approval,
timeout, retry, idempotency, HTTP tools, MCP tools or discovery, persistent
tool definitions, traces, usage metrics, agent max-steps or per-agent tool-call
limits, checkpoints, pause/resume, or HITL.
