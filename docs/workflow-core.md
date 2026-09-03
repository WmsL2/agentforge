# AgentForge Workflow Core — v0.2

## Scope

v0.2 delivers AgentForge's self-built Workflow Core on top of the v0.1 web-engineering foundation. It supports authenticated workflow definition CRUD, validated DAGs, deterministic sequential execution, run lifecycle persistence, and run history backed by PostgreSQL.

It does not implement CONDITION execution, loops, AGENT or TOOL nodes, MCP execution, checkpoints, pause/resume, cancel/retry, Human-in-the-Loop controls, workflow Celery execution, durable intermediate RUNNING checkpoints, Run Step records, or Trace observability.

## Core terminology

| Term | Concrete type / role |
|---|---|
| `WorkflowDefinition` | Python domain object that describes how a workflow should execute. |
| `WorkflowRun` | Python domain object that records one execution's input, lifecycle, outputs, and error. |
| `Workflow` | SQLAlchemy ORM class / instance persisted in the `workflows` table. |
| `WorkflowRun` ORM | SQLAlchemy ORM class / instance persisted in the `workflow_runs` table. It is distinct from the domain `WorkflowRun`. |
| `WorkflowNode` / `WorkflowEdge` | Domain objects representing graph nodes and directed edges. |
| `WorkflowEngine` | Application-owned execution engine class; an instance validates and schedules a definition. |
| `NodeExecutor` | Protocol boundary that defines what it means to execute one node. |
| `NodeExecutionContext` | Frozen context passed to a `NodeExecutor` instance. Its mapping fields are shallow read-only copies; nested mutable values are not deep-frozen. |
| `NodeExecutionResult` | Executor result returned to the engine. |

`WorkflowDefinition` answers **how should this workflow run?** `WorkflowRun` answers **what happened in this execution?** One definition can have many runs.

## Definition and Run

```text
WorkflowDefinition domain object
    |
    | supplies nodes, edges, entry_node_id, and revision to execute()
    v
WorkflowEngine instance

WorkflowRun domain object
    |
    | WorkflowRunService passes this Run object to execute(); it carries this run's input
    v
WorkflowEngine instance
    |
    | calls run.start()/complete()/fail() and writes node_outputs, output, and error
    v
WorkflowRun domain object
```

The definition is the execution description read by the engine. The run carries the mutable state of one attempt; the two `WorkflowRun domain object` labels above refer to the same mutable object. A persisted run stores both `workflow_revision` and `definition_snapshot`, so later edits to a workflow do not erase the graph used by an earlier run.

## HTTP to PostgreSQL flow

### Definition creation

```text
HTTP request
type: JSON body
    |
    | FastAPI parses JSON into a WorkflowCreate Pydantic schema
    v
Definition route function
    |
    | passes current_user.id and WorkflowCreate to a WorkflowService instance
    v
WorkflowService instance
    |
    | constructs and validates a WorkflowDefinition domain object; supplies persistence data + AsyncSession
    v
Workflow definition repository function
    |
    | constructs a Workflow SQLAlchemy ORM instance and calls flush()
    v
Request-scoped AsyncSession instance
    |
    | sends INSERT through asyncpg
    v
PostgreSQL workflows table
```

### Run creation and execution

```text
HTTP request
type: workflow_id path parameter + input JSON
    |
    | FastAPI parses WorkflowRunCreate and passes workflow_id, current_user.id, and input
    v
Run route function
    |
    | calls a WorkflowRunService instance
    v
WorkflowRunService instance
    |
    | asks WorkflowService to load the workflow by id and verify row.user_id == current_user.id
    v
WorkflowDefinition domain object
    |
    | WorkflowRunService creates a PENDING WorkflowRun domain object, flushes its initial ORM row through the run repository, then passes both objects to execute()
    v
WorkflowEngine instance
    |
    | mutates the same WorkflowRun domain object and returns it
    v
WorkflowRun domain object
    |
    | WorkflowRunService passes the Run to the workflow run repository function
    v
Workflow run repository function
    |
    | maps mutable state to a WorkflowRun ORM instance and flushes it
    v
Request-scoped AsyncSession instance
    |
    | sends UPDATE SQL through asyncpg
    v
PostgreSQL workflow_runs table
```

All workflow resource routes require authentication. The application-service ownership boundary is explicit: `WorkflowService.get_owned_workflow()` asks the repository for a Workflow ORM row by `workflow_id`, then compares `row.user_id` with the current `user_id` and returns NotFound on mismatch. Workflow list and count repository queries are scoped by `user_id`. Run detail and list first verify ownership of the parent Workflow through `get_owned_workflow()` before reading workflow-run data; a cross-owner workflow or run is therefore reported as NotFound rather than revealing its existence.

## Execution flow

```text
WorkflowDefinition domain object + WorkflowRun domain object
    |
    | are passed to WorkflowEngine.execute()
    v
WorkflowEngine instance
    |
    | re-runs WorkflowValidator before starting the run
    v
WorkflowValidationResult
    |
    | when valid, selects the first ready node by definition.nodes declaration order
    v
WorkflowNode domain object
    |
    | is passed with NodeExecutionContext to NodeExecutor.execute()
    v
DeterministicNodeExecutor instance
    |
    | returns NodeExecutionResult.output
    v
WorkflowEngine instance
    |
    | records result.output in WorkflowRun.node_outputs[node.id]
    v
WorkflowRun domain object
```

The built-in deterministic executor supports only these node kinds:

- `START` returns a copy of `workflow_input`.
- `VALUE` returns `node.config.get("value")`.
- `END` returns a dictionary of its direct `upstream_outputs`.

The engine creates final `WorkflowRun.output` from END results only, keyed by END node id. For a `START → VALUE(42) → END` graph, it is `{"end": {"value": 42}}`.

## Scheduler and validation

Scheduling is deterministic and sequential. The engine selects the first ready node in `definition.nodes` declaration order. A fan-out can make several nodes ready, but they still execute one at a time in that order. A fan-in node waits for every direct predecessor to finish.

`WorkflowValidator` enforces a validated DAG: non-empty unique nodes and edges; no dangling endpoints or self-loops; exactly one START; an explicit `entry_node_id` that names that START; at least one END; no incoming START edge or outgoing END edge; no cycles; reachability from entry; and only END sinks. It reports validation codes for duplicate, dangling, cycle, unreachable, terminal, and START/entry/END violations. An edge with `condition != None` produces `unsupported_edge_condition`: CONDITION execution semantics are not implemented.

## Persistence

```text
Workflow ORM row
    |
    | definition JSONB is deserialized
    v
WorkflowDefinition domain object

WorkflowRun domain object
    |
    | mutable lifecycle state is serialized
    v
WorkflowRun ORM object
    |
    | repository flushes INSERT or UPDATE through AsyncSession
    v
workflow_runs table
```

`workflows` stores `id`, `user_id`, `name`, `description`, `definition` JSONB, `revision`, `created_at`, and `updated_at`. `workflow_runs` stores `id`, `workflow_id`, `workflow_revision`, `definition_snapshot`, `status`, `input`, `node_outputs`, `output`, `error`, `started_at`, `finished_at`, `created_at`, and `updated_at`. `workflows.user_id → users.id` and `workflow_runs.workflow_id → workflows.id` both use `ON DELETE CASCADE`.

The current Alembic head is `0034_align_workflow_updated_at`. It aligns `workflows.updated_at` with the ORM timestamp contract: nullable with no server default.

`definition_snapshot` and `workflow_revision` are recorded at run creation to preserve historical execution context even after a workflow definition is revised.

## Transaction boundary

HTTP requests use a request-scoped `AsyncSession` from `get_db_session`. On successful request completion, the dependency commits; if an exception escapes, it rolls back. Repositories call `flush()`, never `commit()`.

For the synchronous v0.2 run API, the service creates a PENDING run and flushes it, then the engine transitions it in Python from `PENDING → RUNNING → COMPLETED` or `PENDING → RUNNING → FAILED`. The terminal state is flushed, and the session dependency commits only after the HTTP request succeeds. Therefore RUNNING is not an independently durable, externally observable checkpoint; there is no crash recovery or background workflow worker in v0.2.

## Failure semantics

```text
DeterministicNodeExecutor or a future executor
    |
    | raises an Exception while executing a node
    v
WorkflowEngine instance
    |
    | creates WorkflowRunError(code="node_execution_failed") and calls run.fail(...)
    v
FAILED WorkflowRun domain object
    |
    | is serialized and flushed by the run repository
    v
PostgreSQL workflow_runs row
```

If the engine's initial validation fails, it raises `WorkflowExecutionValidationError`. The application service converts that result to `ValidationError`; the request transaction rolls back, so no invalid PENDING run is left behind.

## API

All paths are authenticated and are rooted at `/api/v1/workflows`.

| Definition API | Method |
|---|---|
| `/api/v1/workflows` | `POST`, `GET` |
| `/api/v1/workflows/validate` | `POST` |
| `/api/v1/workflows/{workflow_id}` | `GET`, `PATCH`, `DELETE` |

| Run API | Method |
|---|---|
| `/api/v1/workflows/{workflow_id}/runs` | `POST`, `GET` |
| `/api/v1/workflows/{workflow_id}/runs/{run_id}` | `GET` |

## PostgreSQL integration verification

`backend/tests/integration/workflow/test_postgres_roundtrip.py` is opt-in: set `AGENTFORGE_RUN_POSTGRES_INTEGRATION=1`. It refuses to run outside the disposable `agentforge_v02_verify` database and otherwise skips in the normal test suite.

The test proves the chain from HTTP request through FastAPI, application services, workflow domain objects, `WorkflowEngine`, `NodeExecutor`, repositories, `AsyncSession`, and PostgreSQL. Its deterministic graph asserts `START output == run_input`, `VALUE output == 42`, `END output == {"value": 42}`, and final output `== {"end": {"value": 42}}` from both the HTTP response and persisted ORM row.

## Runtime boundary and future direction

The Workflow Engine is not built on LangGraph. LangGraph is inherited agent/reference capability and may become a future runtime adapter. The unimplemented future boundary is:

```text
WorkflowEngine
    |
    | future: passes an Agent node to an executor
    v
AgentNodeExecutor
    |
    | future: delegates agent execution
    v
AgentRunner protocol
    ├── NativeAgentRunner
    └── LangGraphAgentRunner
```

`AgentNodeExecutor`, `AgentRunner`, and `LangGraphAgentRunner` are future work, not v0.2 classes or capabilities.

## Known limitations

v0.2 deliberately excludes conditional branches, loops, parallel execution, Agent/Tool/MCP nodes, retries, timeouts, cancellation, checkpointing, pause/resume, HITL, durable running state, background execution, Run Steps, Traces, and enterprise workspace/RBAC boundaries. The current engine is a small validated-DAG execution core, not a complete agent-runtime or orchestration platform.
