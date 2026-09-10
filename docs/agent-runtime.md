# Agent Runtime — v0.4

## Scope

v0.3 introduced a small, stateless Agent Runtime into the Workflow Core. v0.4
adds Tool Platform binding and the LangGraph tool-calling loop to that same
runtime. The runtime remains stateless: it has no memory, checkpoints, thread
state, or persistent conversation history.

## Runtime contracts

`AgentExecutionRequest` carries an `instruction`, generic `input`, optional
`model`, and read-only metadata. `AgentExecutionResult` returns generic
`output` and read-only metadata. `AgentRuntimeError` is the runtime-level
failure type; the runner uses it to translate LangGraph or provider failures.
`AgentRunner` is the framework-independent SPI with one async `run(request)`
method.

An `AGENT` `WorkflowNode` uses the ordinary workflow node model. Its config
requires a non-empty `runner` (currently `langgraph`) and `instruction`; its
`model` is optional and, when provided, must be non-empty.

## Execution boundary

```text
WorkflowDefinition
  | ready AGENT node
  v
WorkflowEngine
  | schedules when the node may execute; supplies WorkflowNode + NodeExecutionContext
  v
DispatchingNodeExecutor
  | selects an executor from node.kind
  v
AgentNodeExecutor
  | combines node config and context.upstream_outputs into AgentExecutionRequest
  v
AgentRunner Protocol
  | framework-independent execution boundary
  v
LangGraphAgentRunner
  | invokes the model
  v
OpenAI-compatible model client
  | sends a model request through the compatible protocol
  v
Configured LLM provider
  | returns AIMessage
  v
LangGraphAgentRunner
  | AIMessage without tool_calls -> AgentExecutionResult
  `-- AIMessage with tool_calls
        v
      ToolNode
        v
      LangGraphToolAdapter
        | creates ToolExecutionRequest
        v
      ToolExecutionService
        | Registry / Validator / Executor
        v
      ToolExecutionResult
        v
      ToolMessage
        v
      LangGraphAgentRunner
```

`WorkflowEngine` decides **when** a node executes. `DispatchingNodeExecutor`
decides **which** executor receives its kind. A concrete `NodeExecutor` executes
one node only. For AGENT nodes, `AgentNodeExecutor` maps `config.runner`,
`config.instruction`, optional `config.model`, and
`NodeExecutionContext.upstream_outputs` into the runner request.

## LangGraph runner

`LangGraphAgentRunner` maps instruction to `SystemMessage`, rendered input to
`HumanMessage`, and chooses `request.model` or `settings.AI_MODEL`. Without
tools, its graph is `START -> model -> END`. With tools, it binds
`StructuredTool` instances and runs:

```text
START -> model -> tools_condition
                  |-- no tool calls --> END
                  `-- tool calls --> tools -> model
```

`add_messages` retains the message history within one graph invocation so a
second model call sees the tool call and `ToolMessage`. It does not create
memory beyond that invocation.

The runner uses an OpenAI-compatible client, which is a protocol choice rather
than a commitment to a particular provider. `LLM_PROVIDER` is identity and
metadata only; the runner has no provider-specific branches.

## Configuration and composition

Platform Runtime configuration is `LLM_PROVIDER`, `LLM_API_KEY`, optional
`LLM_BASE_URL`, `AI_MODEL`, and `AI_TEMPERATURE`. An empty `LLM_BASE_URL`
uses the compatible client's default endpoint. `OPENAI_API_KEY` remains only
for the legacy template chat subsystem.

`backend/app/api/deps.py` is the composition root. It wires
`WorkflowEngine -> DispatchingNodeExecutor -> AgentNodeExecutor -> AgentRunner
-> LangGraphAgentRunner`, plus the production Tool Platform and its
`current_datetime` tool. Concrete dependencies do not leak into runtime
contracts.

## Failure and verification boundaries

Provider, LangGraph, and uncaught tool failures become `AgentRuntimeError`.
`ToolNode(handle_tool_errors=False)` lets a `ToolExecutionError` reach the
runner boundary as the exception cause. During workflow execution,
`WorkflowEngine` normalizes executor exceptions into the current `WorkflowRun`
failure semantics: a failed run has `node_execution_failed` and the failing
node id.

`tests/integration/workflow/` is opt-in PostgreSQL HTTP-to-persistence E2E. It
uses a real platform stack but substitutes `FakeAgentRunner` at the external
runtime boundary. `tests/integration/agent_runtime/` is a separate strict
opt-in live smoke test using the real configured compatible provider.
