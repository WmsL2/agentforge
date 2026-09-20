# Execution Observability — v0.7

## Scope

v0.7 answers: “what actually happened during this `WorkflowRun`?” v0.6 answers
the different question: “where can execution safely resume after interruption
or crash?” Execution observability builds on durable execution; it does not
replace recovery semantics or schedule work.

## Three durable perspectives

`WorkflowRun` is the current overall lifecycle state. `WorkflowCheckpoint` is
the authoritative recovery snapshot. `RunStep` and `TraceEvent` are historical
facts about execution:

```text
WorkflowRun
├── WorkflowCheckpoint — recovery truth
├── RunStep            — one actual NodeExecutor.execute() attempt
└── TraceEvent         — append-only history
```

Resume reads the latest checkpoint, not steps or traces. Historical records
must never be used to infer `completed_node_ids` or choose the next node.

## RunStep semantics

One `RunStep` represents one real `NodeExecutor.execute()` attempt. Its
sequence is per run, begins at 1, and increases monotonically across restart.
The supported states are `running`, `completed`, `failed`, and `interrupted`;
there is no `pending` state. An approval decision does not create a second
approval RunStep: the original approval execution attempt remains an immutable
`interrupted` history record.

## TraceEvent semantics

Trace events are append-only. Current event kinds are:

```text
node_started       node_completed       node_failed       node_interrupted
approval_requested approval_approved    approval_rejected
agent_started      agent_completed      agent_failed
tool_started       tool_completed       tool_failed
```

`step_id` is nullable. `approval_approved` and `approval_rejected` are
run-level events and therefore have `step_id=None`.

## Observer boundary

`WorkflowExecutionObserver` separates the pure execution boundary from
application-owned observation. It offers `start_step`, `complete_step`,
`fail_step`, `interrupt_step`, and `record_event`. The
`NoOpWorkflowExecutionObserver` lets the Engine run without a durable observer.

The Engine orders successful work as:

```text
start_step → NodeExecutor.execute → complete/fail/interrupt observation
           → authoritative WorkflowRun / WorkflowCheckpoint persistence
```

Observation describes execution; it never controls it.

## Agent, tool, and approval tracing

Trace identity flows through the runtime path:

```text
RunStep.step_id → NodeExecutionContext.step_id → AgentExecutionRequest
→ ContextVar → LangGraphToolAdapter → ToolExecutionRequest
```

The Tool Platform remains workflow-independent. Its workflow adapter maps
tool lifecycle callbacks into trace events. This traces tool calls made by an
agent; it does not claim to trace internal LangGraph graph nodes.

## Transaction and crash semantics

The SQLAlchemy observer owns short-lived independent `AsyncSession`
transactions. This keeps observation fail-open, permits `start_step` to commit
a `RUNNING` step before executor invocation, and preserves Trace as historical
fact rather than recovery truth.

A process crash may therefore leave a stale `RUNNING` RunStep: `node_started`
was committed, but no `node_completed`, `node_failed`, or `node_interrupted`
event exists. v0.7 intentionally does not repair such records.

## Query API

Both endpoints require authentication and workflow/run ownership:

```text
GET /api/v1/workflows/{workflow_id}/runs/{run_id}/steps
GET /api/v1/workflows/{workflow_id}/runs/{run_id}/trace
```

Steps are ordered by `sequence ASC`; traces by `created_at ASC, id ASC`.
`duration_ms` is an API computed read-model field, not persisted data. An
unfinished running step returns `duration_ms=null`.

## PostgreSQL recovery proof

PostgreSQL restart/crash integration coverage verifies cross-session durable
facts, approval restart, no re-execution of completed nodes, continuous
RunStep sequence allocation, recovery after a resolution-checkpoint crash, and
the permitted stale `RUNNING` step.

## Non-goals

- Frontend observability dashboard
- OpenTelemetry, LangSmith, Prometheus, or Grafana integration
- Token or cost accounting
- Distributed tracing
- Automatic stale-step repair, recovery scanner, or background recovery worker
- Retry, timeout, condition, loop, or parallel execution
- Workflow TOOL node, workspace/RBAC, frontend workflow editor, or MCP HTTP/OAuth
