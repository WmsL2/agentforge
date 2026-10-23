# AgentForge v0.9 Release Notes — Draft

> Draft only. This document does not create a Git tag or a formal release.

## Highlights

- Background Workflow Execution through Celery after durable PostgreSQL Run
  creation.
- PostgreSQL Execution Claim / Lease / Fencing: a worker writes only while it
  owns the database-issued token, generation and unexpired lease.
- Async Run API and Async Approval Resume, both committing durable state before
  attempting broker publication.
- Recovery Scanner with fair, bounded PostgreSQL `FOR UPDATE SKIP LOCKED`
  selection and persisted redispatch scheduling.
- Real isolated PostgreSQL, Redis and Celery proof jobs in CI.

## Database migration

Deploy migrations in order through Alembic head:

```bash
uv run --directory backend alembic upgrade head
uv run --directory backend alembic current
```

The relevant chain is `0040_harden_workflow_workspace_scope` →
`0041_add_workflow_execution_claim_lease` →
`0042_add_workflow_recovery_dispatch_schedule`. Do not run destructive
downgrades against a business database as part of deployment validation.

## Configuration

Background execution requires the normal PostgreSQL configuration plus:

```text
CELERY_BROKER_URL=redis://<host>:6379/0
CELERY_RESULT_BACKEND=redis://<host>:6379/0
```

The CI-only proof toggles `AGENTFORGE_RUN_POSTGRES_E2E`,
`AGENTFORGE_RUN_ASYNC_API_E2E`, `AGENTFORGE_RUN_ATOMIC6_E2E`, and
`AGENTFORGE_RUN_ATOMIC7_E2E` are not production feature switches.

## API behavior

`POST /api/v1/workflows/{workflow_id}/runs/async` returns `202 Accepted` only
after the Run is committed. The approval async endpoint follows the same
commit-before-publish ordering. A broker publication failure returns `503` but
does not erase the durable recoverable state; the scanner may dispatch it later.

## Verification evidence

- Atomic 5 CI gate: five PostgreSQL / HTTP / Redis / Celery E2E tests with a
  strict zero-skip JUnit count.
- Atomic 6 CI gate: eleven recovery and approval PostgreSQL / Redis / Celery
  tests with a strict zero-skip JUnit count.
- Atomic 7 CI gate: six PostgreSQL release proofs covering concurrent claim,
  lease takeover, fencing, rollback, constraints and final migration schema.

## Known limits

- Delivery is at-least-once; external effects are not exactly-once.
- No transactional outbox, automatic heartbeat, generic retry framework or
  HTTP idempotency key is introduced by v0.9.
- PostgreSQL is required for the release proof; SQLite is not an equivalent
  substitute for Claim / Lease / Fencing behavior.

## Deployment checklist

1. Back up the production database and confirm the target connection.
2. Apply Alembic upgrades to head; do not downgrade as a smoke test.
3. Confirm Redis connectivity and start Celery workers before enabling async
   traffic.
4. Confirm the worker registers `agentforge.workflow.execute`.
5. Verify CI proof jobs and inspect application metrics/logs after deployment.
