# AgentForge v0.10 Release Notes

> This document describes the v0.10.0 release line. At version-alignment time,
> the latest formal GitHub Release was v0.9.0. This document does not create a
> branch, tag, GitHub Release or deployment; consult repository tags and GitHub
> Releases for current publication status.

## 1. v0.10 Overview

v0.10 adds the Workflow Frontend to the durable, Workspace-scoped execution
platform delivered through v0.9. It connects the existing Next.js application
to Workspace, Workflow, execution, observability and human-approval APIs and
adds a visual editor plus an execution inspector. It does not replace the
PostgreSQL checkpoint, claim, lease, fencing or Celery recovery model.

The release-preparation scope is frontend-focused. No new database migration or
backend execution contract is introduced by v0.10.

The repository uses one full-stack release version for this release line.
`backend/pyproject.toml`, the installed Python distribution, `app.__version__`,
FastAPI application metadata, CLI `--version` output and the private
`frontend/package.json` are aligned to `0.10.0`. Automated regression tests keep
these surfaces synchronized. Version metadata alone is not publication evidence.

## 2. Frontend API Integration

The browser calls same-origin Next.js `/api` routes. Those routes read the
authenticated access-token cookie, forward a bearer token through
`backendFetch`, encode dynamic path segments, allow only declared query
parameters and preserve relevant backend status and error bodies. Async Run and
approval-resume routes preserve `202 Accepted` and expose a same-origin
`Location` for the created or resumed Run.

The typed frontend clients cover:

- Workspace CRUD and membership operations;
- Workflow CRUD and graph validation;
- asynchronous Run submission and Run history;
- Run detail, RunStep and TraceEvent queries; and
- pending Approval lookup, asynchronous approval and rejection.

Authentication and authorization remain server responsibilities. Client-side
guards improve the user experience but do not replace FastAPI Workspace policy.

## 3. Workspace & Workflow Management

The management screen provides Workspace selection, creation, update and
deletion, membership listing and role management, and paginated Workflow CRUD.
Workspace identity is carried through the URL and React Query keys so cached
data does not cross Workspace boundaries.

New Workflows start from a legal START-to-END graph. Destructive actions use
confirmation flows and pending-operation locks. Mutation failures retain the
current context rather than silently navigating away.

## 4. Visual Workflow Canvas

The React Flow v12 canvas supports START, VALUE, AGENT, APPROVAL and END nodes.
The schema adapter keeps the backend `WorkflowGraph` authoritative while storing
canvas position in node metadata. IDs, kinds, configuration, metadata, edge
conditions, ordering, entry node and schema version are preserved.

Local rules reject duplicate edges, self-loops, missing endpoints, edges into
START, edges from END, cycles, START deletion and deletion of the final END.
Selection and measured dimensions are presentation state and do not mark the
graph dirty or mutate business configuration.

Validation and save operate on a stable snapshot. Pending validation/save,
stale responses, revision conflicts and newer server revisions cannot silently
overwrite local work. Dirty graphs and unapplied drafts are protected during
in-app navigation and browser unload.

## 5. Node Configuration Editor

The Inspector provides node-specific editing with explicit Apply semantics:

- VALUE accepts the supported JSON value types while distinguishing a missing
  value from explicit `null`;
- AGENT exposes runner, instruction, model and configuration fields; and
- APPROVAL exposes the approval prompt configuration.

JSON input rejects non-finite values and unsafe integers instead of coercing
them to `null` or silently losing precision. Invalid edits remain in the draft
for correction. Drafts are isolated per node and are not written into the
saved graph until Apply succeeds.

## 6. Workflow Execution UI

The execution panel submits only the JSON input for the currently saved
Workflow revision. It never uploads an unsaved CanvasGraph with a Run request.
Submission is disabled while the graph or Inspector draft is unsaved, during
validation/save, and while a revision conflict is unresolved.

Accepted asynchronous submissions are displayed as accepted/pending rather
than completed. Run history is paginated and cached by user, Workflow, Run and
page identity. Active Runs poll at bounded intervals; terminal transitions
perform a final bounded refresh of Steps, Trace and history. Manual refresh
remains available.

Request-generation guards prevent a late response from Workflow A from
overwriting Workflow B after navigation. Dispatch failures that contain a
durably created Run ID retain that Run and do not automatically resubmit it.

## 7. Run Inspector & Human Approval

The Run Inspector renders server-provided status, Workflow revision, input,
output, error, definition snapshot, RunSteps and TraceEvents. Historical Runs
use their immutable `definition_snapshot`; they are not reconstructed from the
currently editable Workflow. Large JSON is shown through a bounded preview
while the copy action retains the complete value.

For a PAUSED Run, trusted OWNER and ADMIN memberships may view a pending prompt,
enter an optional decision note, approve asynchronously or reject. MEMBER may
inspect an authorized Run but the frontend neither queries pending approval nor
offers decision controls. Approval actions require a matching Run, PAUSED Run
state, PENDING Approval and successfully loaded membership. Synchronous locks
prevent double submission, and conflict responses trigger related-data refresh.

## 8. Workspace RBAC

The frontend mirrors, but does not redefine, backend Workspace authorization:

| Capability                                  | OWNER | ADMIN | MEMBER |
| ------------------------------------------- | :---: | :---: | :----: |
| View authorized Workspace and Workflow data |  Yes  |  Yes  |  Yes   |
| Manage Workspace identity/deletion          |  Yes  |  No   |   No   |
| Manage non-owner memberships                |  Yes  |  Yes  |   No   |
| Create and edit Workflows                   |  Yes  |  Yes  |  Yes   |
| Delete Workflows                            |  Yes  |  Yes  |   No   |
| Submit/view authorized Runs                 |  Yes  |  Yes  |  Yes   |
| Decide pending approvals                    |  Yes  |  Yes  |   No   |

The backend remains authoritative and uses membership-scoped policy, including
anti-enumeration behavior. A global application administrator does not gain a
Workspace bypass merely from the frontend role display.

## 9. Data Contracts

### `WorkflowGraph`

`WorkflowGraph` contains `entry_node_id`, ordered `nodes`, ordered `edges`,
`schema_version` and graph metadata. Each node has an ID, kind, configuration
and metadata. Each edge has an ID, source, target, nullable condition and
metadata.

### `WorkflowRun`

`WorkflowRun` identifies the Workflow and saved revision and carries an
immutable `definition_snapshot`, lifecycle status, JSON input, node outputs,
final output, structured error and timestamps. Supported UI states are
PENDING, RUNNING, PAUSED, COMPLETED, FAILED and CANCELLED.

### `RunStep`

`RunStep` is an execution-attempt summary with sequence, node identity and kind,
status, input, nullable output, nullable error, metadata, timestamps and
duration. It is observability data, not the recovery source of truth.

### `TraceEvent`

`TraceEvent` is append-only execution history containing Run identity, nullable
Step identity, event kind, JSON payload and creation time. Node, approval, agent
and tool lifecycle kinds are represented. Checkpoints—not Steps or TraceEvents—
remain the source of truth for durable resume.

## 10. CI & Test Evidence

The evidence classes must not be conflated:

1. **Frontend unit/component tests:** Vitest exercises API clients, adapters,
   canvas rules, management, editor, execution, RBAC and async race behavior.
2. **Browser integration:** Playwright runs real Chromium against the real
   Next.js UI. Authentication setup uses the CI test backend, while
   `workflow-execution.spec.ts` controls Workflow API responses for deterministic
   Run, polling, approval and cross-Workflow race scenarios. This is not a real
   Celery execution proof.
3. **Backend integration proofs:** dedicated CI jobs use disposable PostgreSQL
   16 and Redis 7 services. The configured strict gates require 5 Atomic 5
   async/API tests, 11 Atomic 6 recovery/approval tests and 6 Atomic 7
   PostgreSQL release proofs, all with zero failures, errors and skips.

The regular CI workflow additionally runs backend Ruff, formatting, type checks,
the backend pytest suite, dependency audit, container security checks, frontend
lint, frontend type checking and frontend coverage. The frontend CI job runs
`auth.spec.ts`, `home.spec.ts` and `workflow-execution.spec.ts` on Chromium.

### Local release-preparation evidence

On 2026-11-03, at Git commit
`c6a7c0aed6550cd76e0766c314d652c7da8d038b`, the documented frontend commands
produced the following local results:

- `bun install --frozen-lockfile`: 839 installs across 950 packages checked,
  with no dependency changes;
- `bun run lint`: completed with 0 errors and 13 warnings in pre-existing chat,
  UI and generated coverage files;
- `bun run type-check`: completed successfully;
- `bun run test:run`: 20 test files and 215 tests passed;
- `bun run test:coverage`: 20 test files and 215 tests passed, with 58.85%
  statements, 100% branches, 47.82% functions and 58.85% lines in the configured
  coverage scope; and
- `bun run build`: completed successfully and generated 105 static pages, while
  retaining the existing accessibility warnings.

The complete Chromium command with authentication setup was not run in this
release-preparation session: neither the local backend health endpoint nor
explicit `TEST_USER_EMAIL` / `TEST_USER_PASSWORD` credentials were available.
An existing storage-state file was not treated as sufficient evidence of a
current authenticated environment. This is an explicit verification gap, not a
browser-test success result.

### Local version-alignment evidence

On 2026-11-03, starting from Git commit
`97b31e27c0f14703df9a6bc521cbef68e618b107`, local version-alignment validation
confirmed Python distribution metadata, `app.__version__`, FastAPI application
metadata, CLI output and the frontend package version as `0.10.0`.

- the targeted version suite passed 3 tests;
- the full backend suite passed 919 tests and skipped 89 explicitly gated tests;
- backend Ruff and format checks passed, while `ty check` completed with two
  pre-existing warnings;
- the frontend unit and coverage runs each passed 215 tests in 20 files; and
- the frontend production build completed successfully.

`backend/uv.lock` changed only the editable AgentForge root package from
`0.9.0` to `0.10.0`. `frontend/bun.lock` did not change because its workspace
record does not store the private root package version; frozen installation
completed without dependency changes.

Release reviewers must use the latest CI run as the authoritative remote result.
Counts recorded by local release preparation describe only that checkout and
must not be reused after the test suite changes.

## 11. Known Limitations

- Publishing v0.10.0 still requires an authorized human to create the Git tag
  and GitHub Release; this document and aligned metadata are not publication
  evidence.
- The Workflow Playwright suite uses controlled API responses. It validates
  browser integration and user-visible races, not a single real-browser →
  FastAPI → PostgreSQL → Redis → Celery → worker completion journey.
- A fully authenticated real-user Workflow flow against the complete local
  backend stack is not established by the controlled browser suite.
- Background delivery remains at-least-once. External side effects are not
  exactly-once, and v0.10 does not add a transactional outbox, generic retry or
  timeout framework, or HTTP idempotency key.
- Conditional, loop and parallel Workflow constructs, a first-class Workflow
  TOOL node, token/cost accounting, and MCP HTTP/OAuth remain outside scope.
- Frontend CI runs lint, type checking, coverage and selected Chromium specs;
  the explicit `bun run build` release check is currently a local verification
  step rather than a dedicated frontend CI step.

## 12. Deployment & Verification

### Backend and infrastructure

1. Back up the target database and verify the connection.
2. Apply and inspect migrations:

   ```bash
   uv run --directory backend alembic upgrade head
   uv run --directory backend alembic current
   ```

3. Confirm PostgreSQL and Redis connectivity and start FastAPI, Celery workers,
   Celery Beat and Flower using the existing deployment configuration.
4. Confirm workers register `agentforge.workflow.execute` and inspect the latest
   CI backend proof jobs before enabling asynchronous traffic.

### Frontend

Install and verify the exact locked dependency set:

```bash
cd frontend
bun install --frozen-lockfile
bun run lint
bun run type-check
bun run test:run
bun run test:coverage
bun run build
```

With the authenticated test environment running, execute the selected Chromium
suite used by CI:

```bash
bunx playwright test \
  e2e/auth.spec.ts \
  e2e/home.spec.ts \
  e2e/workflow-execution.spec.ts \
  --project=chromium
```

### Manual release acceptance

Before an authorized release, verify with a disposable non-production account:

1. log in and select a Workspace;
2. exercise OWNER, ADMIN and MEMBER boundaries;
3. create, edit, validate and save a Workflow;
4. submit the saved revision and observe PENDING through a terminal state;
5. inspect RunSteps and TraceEvents from the backend-generated Run;
6. pause at an APPROVAL node, approve and reject separate Runs; and
7. confirm the worker, database and UI agree after refresh and re-login.

This manual/full-stack acceptance is separate from the controlled Playwright
suite and must be reported explicitly if it has not been performed.
