# Agent Runtime — v0.3

## Scope

v0.3 integrates a small, stateless Agent Runtime into the existing Workflow
Core. It adds contracts, the `AGENT` workflow node, node-kind dispatch, a
LangGraph-backed runner, production dependency composition, PostgreSQL E2E
coverage, and an opt-in live provider smoke test. It does not add tools, MCP,
memory, checkpoints, streaming, retries, cancellation, traces, token usage,
background execution, conditional branches, loops, or parallel execution.

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
  | runs START -> model -> END
  v
OpenAI-compatible model client
  | sends the configured request through the compatible protocol
  v
Configured provider
  | returns model content
  v
AgentExecutionResult
  | becomes NodeExecutionResult
  v
WorkflowRun.node_outputs
```

`WorkflowEngine` decides **when** a node executes. `DispatchingNodeExecutor`
decides **which** executor receives its kind. A concrete `NodeExecutor` executes
one node only. For AGENT nodes, `AgentNodeExecutor` maps `config.runner`,
`config.instruction`, optional `config.model`, and
`NodeExecutionContext.upstream_outputs` into the runner request.

## LangGraph runner

`LangGraphAgentRunner` is stateless: it stores no history, checkpoints, thread
state, or memory. It maps instruction to `SystemMessage`, rendered input to
`HumanMessage`, and chooses `request.model` or `settings.AI_MODEL`. Its graph
is exactly `START -> model -> END`.

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
-> LangGraphAgentRunner`; concrete dependencies do not leak into runtime
contracts.

## Failure and verification boundaries

Provider or LangGraph failures become `AgentRuntimeError`. During workflow
execution, `WorkflowEngine` normalizes executor exceptions into the current
`WorkflowRun` failure semantics: a failed run has `node_execution_failed` and
the failing node id.

`tests/integration/workflow/` is opt-in PostgreSQL HTTP-to-persistence E2E. It
uses a real platform stack but substitutes `FakeAgentRunner` at the external
runtime boundary. `tests/integration/agent_runtime/` is a separate strict
opt-in live smoke test using the real configured compatible provider.
