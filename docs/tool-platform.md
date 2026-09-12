# Tool Platform & MCP Integration — v0.5

## Scope

v0.4 established the framework-independent AgentForge Tool Platform. v0.5
adds MCP integration and discovery without moving MCP SDK types into the Tool
Platform core. The core still defines a tool, validates JSON Schema arguments,
resolves registrations, and provides one uniform execution boundary. LangGraph
is an integration consumer, not the registry or executor implementation.

## Domain contracts

- `ToolDefinition` describes a tool: its name, description, JSON Schema input,
  and metadata.
- `ToolExecutionRequest` identifies one tool invocation and its arguments.
- `ToolExecutionResult` carries generic output and metadata.
- `ToolExecutionError` is the Tool Platform's uniform execution error boundary.

`ToolSchemaValidator` interprets schemas as JSON Schema Draft 2020-12.
`ToolExecutor` is the asynchronous execution SPI, and `ToolRegistration`
combines a definition with its executor.

`ToolRegistry.definitions()` returns an ordered snapshot of public
`ToolDefinition` descriptors. It is the read surface for dynamic binding;
executors remain private to registrations.

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

## MCP discovery, registration, and lifecycle

MCP contracts define framework-independent descriptors, call results, and
errors. `MCPSDKClientAdapter` and `open_stdio_mcp_client` isolate the official
SDK and stdio transport in concrete integration modules.

For each configured server, `MCPToolDiscovery` preserves the remote order and
maps each remote name to `namespace__remote_name` for local registration. For
example, remote `github/create_issue` is registered as
`github__create_issue`; the LLM sees the local name while `MCPToolExecutor`
calls `create_issue` on the GitHub MCP client.

`MCPToolDiscovery` maps remote descriptors into local `ToolDefinition` values
and `MCPDiscoveredTool` records. `MCPToolRegistrationService` then creates the
`MCPToolExecutor` bound to each remote name and registers the discovered
definition/executor pair in `ToolRegistry`. `open_tool_platform()` creates the
application-scoped registry, registers native `current_datetime`, then opens
configured MCP registrations. It keeps stdio clients alive until the
application lifespan exits.

## LangGraph adapter and agent loop

`LangGraphToolAdapter.adapt()` converts each `ToolDefinition` from the
`definitions()` snapshot into a `StructuredTool`, retaining the definition's
JSON Schema as the source of truth:

```text
ToolDefinition -> LangGraphToolAdapter.adapt() -> StructuredTool
```

At execution time the adapter creates a `ToolExecutionRequest` and calls only
`ToolExecutionService`; it neither executes Python callables directly nor
accesses `ToolExecutor` directly. This lets both native and MCP tools share one
execution path.

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

## Error boundaries and test coverage

`ToolNode(handle_tool_errors=False)` lets `ToolExecutionError` escape. The
outer `LangGraphAgentRunner.run()` boundary converts it to
`AgentRuntimeError(code="langgraph_execution_failed")`, preserving the original
tool error as the exception cause.

Discovery failures surface during startup/registration before the shared
`ToolRegistry` is exposed. During tool execution, MCP client failures are
translated by `MCPToolExecutor` into `ToolExecutionError`, while remote tool
results with `is_error=True` become
`ToolExecutionError(code="mcp_tool_execution_failed")`. Full offline stdio
tests use a real subprocess server and cover discovery, namespace mapping,
executor calls, lifecycle cleanup, registry snapshots, and agent dynamic
binding.

## Non-goals

v0.5 does not implement HTTP/SSE MCP transport, OAuth, persisted MCP
connections, frontend MCP management, per-agent permissions, policy, approval,
timeout, retry, idempotency, a Workflow TOOL Node, persistent tool definitions,
traces, usage metrics, agent max-steps or per-agent tool-call limits,
checkpoints, pause/resume, or HITL.
