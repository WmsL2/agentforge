# Durable Execution & Human-in-the-Loop — v0.6

## Asynchronous run submission

`POST /api/v1/workflows/{workflow_id}/runs/async` authorizes and validates the
workflow, commits a new `PENDING` run to PostgreSQL, and only then publishes its
run ID to Celery. A `202 Accepted` response means submission was accepted, not
that execution completed. The response is the creation-time snapshot; a fast
worker may already have advanced the persisted state, so clients should follow
the `Location` header and use the existing run GET endpoint for current state.

PostgreSQL commit and Celery publish are not one distributed transaction. If
publish cannot be confirmed, the API returns `503 WORKFLOW_DISPATCH_FAILED` and
retains the committed `PENDING` run for a future recovery scanner. Cancellation
after commit can leave the same recoverable state. This release does not provide
a transactional outbox, exactly-once delivery, or HTTP request idempotency.

v0.6 establishes durable workflow runs, append-only checkpoints, pause/resume,
`APPROVAL` interruption, approval persistence, human decisions, and crash-safe
continuation. It is an AgentForge Workflow Engine capability, separate from a
LangGraph checkpointer:

```text
AgentForge WorkflowEngine
  -> AgentForge WorkflowCheckpoint
  -> NodeExecutor
  -> AgentRunner
  -> LangGraphAgentRunner
```

> **Current main note:** v0.7 adds `RunStep` and `TraceEvent` execution
> observability, and v0.8 adds Workspace-scoped authorization, on top of this
> recovery model. `WorkflowCheckpoint` remains the recovery truth and resume
> still starts from the latest checkpoint. See
> [Execution Observability](execution-observability.md).

## Run lifecycle

```text
PENDING -> RUNNING -> PAUSED -> RUNNING -> COMPLETED
                    \-> CANCELLED
RUNNING -> FAILED
```

`COMPLETED`, `FAILED`, and `CANCELLED` are terminal. Current cancellation is
only `PAUSED -> CANCELLED` and is used by rejection of an approval request.

## Run and checkpoint

`WorkflowRun` answers “what is the overall state of this run?” It stores its
identity, workflow revision, immutable `definition_snapshot`, input, current
public `node_outputs`, final output, error, lifecycle status, and timestamps.

`WorkflowCheckpoint` answers “where exactly did execution reach?” It stores a
per-run sequence, `completed_node_ids`, a `node_outputs` snapshot,
`pending_node_id`, optional interrupt data, and `created_at`. Resume uses the
latest checkpoint; it must not infer completion from `run.node_outputs`, since
`None`, `{}`, and `[]` are all valid node outputs.

Checkpoints are append-only. Their sequence starts at 1, increases monotonically
for each run, and is unique per `(run_id, sequence)`.

## Durable persistence boundary

For a successful node, execution is ordered as follows:

```text
Node executor returns COMPLETED
  -> update run.node_outputs and completed_node_ids
  -> persist Run state
  -> insert Checkpoint
  -> COMMIT
  -> schedule next node
```

`flush` makes SQL visible in the current transaction; `COMMIT` is the durable
recovery boundary.

## Approval interruption and persistence

An `APPROVAL` executor returns `NodeExecutionOutcome.INTERRUPTED`. The engine
pauses the run and writes an interruption checkpoint whose pending node is the
approval node and whose interrupt type is `approval_required`. The approval node
is not completed at this point.

The paused run, interruption checkpoint, and PENDING `ApprovalRequest` are
committed together. Approval data includes `run_id`, `workflow_revision`, node
id, prompt, status, decision user/note, and decision timestamps. Decisions lock
the approval row with `SELECT ... FOR UPDATE`, so concurrent approve/reject
requests are serialized.

## Approve and the resolution checkpoint

For example, an interruption checkpoint can be:

```text
completed: start, before
pending: approval
interrupt: approval_required
```

Approve first creates a normal `WorkflowCheckpoint` that represents resolution:

```text
completed: start, before, approval
pending: None
interrupt: None
node_outputs[approval] = {
  "decision": "approved",
  "approval_id": "...",
  "decided_by": "...",
  "decided_at": "...",
  "decision_note": "..."
}
```

This is not a new checkpoint type. It is a resolution checkpoint: an ordinary
checkpoint that safely records the externally completed approval node.

The ordering is deliberate:

```text
lock Approval row
  -> load Run, definition_snapshot, latest Checkpoint
  -> validate approval/checkpoint consistency
  -> PENDING -> APPROVED
  -> mark APPROVAL externally completed
  -> persist resolution checkpoint
  -> atomically claim PAUSED run as RUNNING with lease/fencing generation
  -> COMMIT
  -> BackgroundRunExecutor.execute_claimed()
```

The synchronous path does not call `Engine.resume()` directly. It commits the
decision, resolution checkpoint, and database execution claim together, then
uses the same fenced background execution path as a worker. If the process
crashes after commit, lease expiry leaves a safe recovery point.

`POST /api/v1/workflows/{workflow_id}/runs/{run_id}/approvals/{approval_id}/approve/async`
uses the same authorization, row lock, snapshot and checkpoint validation, but
returns `202 Accepted` after the approval and resolution checkpoint commit and
after publishing the Run ID to Celery. The worker atomically claims only a
PAUSED run whose approval is APPROVED and whose latest checkpoint is that safe
resolution state; it changes the run to RUNNING in that same claim transaction.
If broker publication fails, the API returns 503 without rolling back the
committed decision. The scanner can discover it later.

Reject instead transitions `PENDING -> REJECTED` and `PAUSED -> CANCELLED` in
one committed transaction. It creates no resolution checkpoint, does not call
`Engine.resume()`, and executes no downstream nodes; the interruption checkpoint
remains the historical execution record.

## Restart recovery

After Session A, Service A, Engine A, and their Python objects disappear, a
fresh PostgreSQL Session and fresh runtime objects can reconstruct state solely
from the `WorkflowRun` row, its `definition_snapshot`, the latest
`WorkflowCheckpoint`, and the `ApprovalRequest`. Completed nodes are skipped.

The run uses `definition_snapshot`, not the current Workflow definition. A
current workflow may be revised while a paused old run remains recoverable under
its original graph revision. Real PostgreSQL restart tests use `NullPool`, new
sessions/connections, and real commits to verify this behavior.

## Automatic recovery scan

Celery Beat periodically invokes a bounded PostgreSQL recovery scan. It selects
PENDING runs without a claim (or with an expired claim), RUNNING runs with an
expired lease, and only the narrowly validated APPROVED PAUSED runs described
above. It never selects waiting/rejected approvals, terminal states, or a valid
lease. Candidates due according to their persisted `recovery_next_dispatch_at`
are ordered by least-recent dispatch, then creation time, and selected with
PostgreSQL `FOR UPDATE SKIP LOCKED`. The scanner writes both the last and next
dispatch timestamps in that same short transaction before releasing locks and
publishing.

Publication can be repeated: this is at-least-once dispatch, not exactly-once
side effects. A worker must still obtain the database-issued claim token,
generation and lease before it can persist work. There is no transactional
outbox, HTTP idempotency key or automatic heartbeat.

## Explicit non-goal

| Capability | v0.6 status |
|---|---|
| Recovery primitives and durable state | Implemented |
| PostgreSQL restart proof | Implemented |
| Automatic recovery scan | Implemented through Celery Beat |
| Background recovery worker | Implemented through existing Celery workers |

The scanner does not retry nodes, guarantee exactly-once external effects, or
replace a transactional outbox.
