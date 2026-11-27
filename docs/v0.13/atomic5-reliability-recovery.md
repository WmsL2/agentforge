# AgentForge v0.13 — Atomic 5 Reliability & Recovery

Local implementation report, 2026-11-27. Final Source Review and Atomic 5
completion remain pending.

## Baseline and review

Verified `D:/agent_project/agentforge`, origin
`https://github.com/WmsL2/agentforge.git`, branch `main`, HEAD
`346bcfd971380c8af7692cf5f74b37b712874550`, peeled v0.12.0
`6e4cca6bc188d829bc09431080b08ad86e37f3fb`, clean worktree and empty staging.
Atomic 4 completion, PR #43 merge, PR CI #205 SUCCESS, Main CI #206 SUCCESS
(16 jobs), local sync and pre-implementation Source Review PASS are supplied
historical evidence. This task ran no new CI.

Reviewed AGENTS.md, the amended roadmap and original audit, Workflow
claim/recovery/durability and async submission/approval, Knowledge repositories,
executor and recovery scanner, document upload/delete and metadata cascades,
API/Redis/session lifecycle, worker/scanner composition and task entry points,
and MCP stdio lifecycle. MCP registration uses AsyncExitStack for entered
clients (`backend/app/integrations/mcp/lifecycle/stdio.py:19`). Redis close
already handles an uninitialized client. Knowledge base and workspace DB
cascades can orphan original files without using the explicit document
delete path. The only application reconciliation call found was the service
delegating to storage. There is no HTTP, startup or Beat caller.

The four worker/scanner composition paths already dispose in finally during
their guarded work. Tests now cover their body cancellation. A separate scope
review item is that all four construct the session maker before the guard, so
a constructor exception there can bypass that disposal. Their existing finally
also has ordinary exception precedence on disposal failure. These composition
implementation files are outside the explicit implementation list and remain
untouched. The corrected task-local context is `get_worker_db_context`.

## Findings and implementation

| Finding | Disposition |
| --- | --- |
| A5-01 | Indexing closes owned, optionally closable providers with a cooperative budget. Retrieval shares the close protocol with its behavior preserved. See `backend/app/services/knowledge/indexing_service.py:167` and `:233`. |
| A5-02 | API attempts Redis and DB disposal independently after tool exit, including partial startup. The worker session and its exit attempt precede engine disposal. See `backend/app/main.py:38` and `backend/app/db/session.py:67`. |
| A5-03 | Upload compensates only after confirmed pre-commit rollback. Commit ambiguity retains the file. See `backend/app/services/knowledge/document_service.py:49` and `:169`. |
| A5-04 | The existing reconciliation path is a sorted relative preview. See `backend/app/services/knowledge/document_storage.py:117` and complete inventory query at `backend/app/repositories/knowledge_document.py:94`. |
| P1-13 | Paired inventory, backup, isolated restore and resume procedures documented in the [recovery runbook](../recovery.md). |
| P1-14 | Destructive snapshot-based reconciliation disabled. Tests preserve in-flight, live and unreferenced files. |
| P2-08 | Paired restore drill NOT RUN. The revised roadmap defers the production drill. RPO/RTO remain unmeasured. |

The indexing job attempts close once for a created closable provider on
success, mismatch, embedding/validation/persistence error, lease loss and
cancellation. Non-closable providers remain compatible. The two-second
close budget is cooperative. Cleanup diagnostics omit exception details.
Close failure cannot rewrite a committed indexing result. New caller
cancellation during close propagates. The heartbeat keeps its renewal interval
and DB fencing. At exit it gets one second to stop before cancellation, then
the executor joins it before subsequent job work and provider close. A driver
that does not cooperate with cancellation can delay the join. Stopping the
heartbeat does not revoke the lease. Pending-job idempotency, commit before
dispatch, atomic active-generation switching and availability of the old
generation after failed reindex remain existing repository contracts.

API cleanup preserves a primary startup, execution or tool-exit failure while
attempting independent disposal. The task-local worker context retains NullPool
and commits on success. A body/commit error or cancellation attempts rollback.
The engine is disposed after the session exit attempt even when construction
or entry fails. Secondary cleanup failures leave the primary error available
to the caller. These tests cover cooperative lifecycle failures, not OS signal
handling or process termination.

Upload only creates metadata after successful storage save. Cancelling an await
does not stop a filesystem thread already writing, so an orphan can remain.
Before commit, the service compensates the file only after confirmed rollback.
An error or cancellation once commit starts may mean the server committed and
the acknowledgement was lost. The service preserves the saved file and original
error, attempts rollback and records DOCUMENT_UPLOAD_COMMIT_UNCERTAIN with the
document ID. The former commit-failure test expected deletion and was replaced
because that outcome could remove an original referenced by durable metadata.
Metadata-first deletion still removes the file only after successful commit.
Filesystem cleanup failure after that commit can leave an orphan.

Preview propagates inventory failure, skips symlinks and resolved aliases under
the storage root, and does not create the root or mutate its contents. A candidate
may be an upload whose metadata is still pending. Preview is a snapshot under an
operator-controlled root and does not guarantee safety against hostile concurrent
directory replacement. Any destructive maintenance needs separate authorization,
quiesced writers and drained transactions/filesystem writes, a refreshed
inventory, reviewed candidates and containment/identity checks. There is no
reconciliation apply path.

## Workflow and integration evidence

Workflow business code is unchanged. The executor loads immutable snapshots
and uses the existing token/generation and database-clock lease checks.
Fenced persistence checks checkpoint sequence and commits run state, checkpoint
and applicable approval state together. Recovery scan publication happens after
its reservation transaction. The existing workflow lease, no added heartbeat,
late acknowledgement and worker-lost rejection behavior is preserved. An
uncommitted node can replay external effects under at-least-once delivery.

Source anchors are `backend/app/services/workflow/application/background/executor.py:62`,
`backend/app/services/workflow/application/background/durability.py:95`,
`backend/app/repositories/workflow/run/claim.py:155`,
`backend/app/services/workflow/application/background/recovery_scanner.py:48`,
`backend/app/services/workflow/application/run/async_service.py:41`,
`backend/app/services/workflow/application/approval/service.py:120` and
`backend/app/services/workflow/execution/engine/engine.py:103`.

New cases cover cancellation after a modeled committed checkpoint, release
failure after durable pause, and scanner inventory failure/publication cancellation.
Existing selected cases cover cancellation before checkpoint, infrastructure
failure retaining lease recovery, lost lease preventing writes, terminal release
failure, and committed PENDING submission before failed publication. Existing
real PostgreSQL files cover independent claim winners, duplicate delivery,
takeover/stale fencing, clock recheck after locking, transaction rollback,
interruption before and after checkpoint, immutable snapshots, approval and
post-publication-failure recovery. Existing CI jobs include
`atomic7-postgres-release-e2e`, `atomic6-recovery-approval-e2e` and
`v011-atomic8-knowledge-lifecycle-e2e`. Those integration definitions were
preserved. Fake sessions and modeled commits are local contract evidence.

## Verification

The existing offline launcher injects synthetic settings and
`AGENTFORGE_ENV_FILE=none` before collection, with loopback port 1 DB/Redis
placeholders and empty provider credentials. The broad selection includes local
synthetic MCP stdio subprocesses and in-memory Celery adapters. It excludes the
separate real service suite under `tests/integration` (singular).

The targeted pre-fix run had **34 failed, 24 passed**, exit 1. It reproduced
missed provider close, early/missing engine disposal, primary error replacement,
file deletion after failed/ambiguous commit or rollback failure, and destructive
reconciliation. The acknowledgement-loss case models durability in a fake
transaction and uses pytest temporary files. New tests also cover renewal in
flight during shutdown or cancellation, provider close timeout, partial API
startup, and successful metadata commit before deletion cleanup.

| Check | Actual result |
| --- | --- |
| Final focused selection | 400 passed, 54 Pydantic warnings, exit 0 |
| Established broader offline selection | 1,335 passed, 150 Pydantic warnings, exit 0 |
| Ruff check app tests cli | Exit 0 |
| Ruff format check app tests cli | Exit 0, 512 files conform |
| ty check | Exit 0, two existing Workflow warnings |

Both final test selections had zero failures and skips. Real PostgreSQL/Redis/
Celery integration, live Provider calls, process shutdown, container verification,
backup/restore and production recovery are NOT RUN. Frontend was not rerun.
Atomic 4 historical frontend evidence remains 1,034 passed. Atomic 3's deferred
production verification remains deferred. No actual private configuration or
media was accessed. No infrastructure startup, dependency installation, network
configuration, Git publication or Atomic 6 work occurred.

Exact commands from the repository root (with distinct result names) follow.

```text
python .cache/atomic4-offline/run.py pytest tests/knowledge/test_document_service.py tests/knowledge/test_document_storage.py tests/knowledge/test_indexing_service.py tests/composition/test_resource_disposal.py -q --tb=line
python .cache/atomic4-offline/run.py pytest tests/workflow/application/background tests/workflow/application/run/test_async_service.py tests/workflow/application/approval/test_service.py tests/workflow/execution/engine/test_recovery.py tests/workflow/persistence/run/repository/test_claim.py tests/knowledge/test_indexing_service.py tests/knowledge/test_index_recovery.py tests/knowledge/test_embedding_provider.py tests/knowledge/test_retrieval_service.py tests/knowledge/test_document_service.py tests/knowledge/test_document_storage.py tests/composition tests/worker tests/api/test_health.py tests/api/test_metrics.py tests/api/test_exceptions.py tests/core/test_operational_observability.py tests/core/test_deployment_contract.py -q --tb=short
python .cache/atomic4-offline/run.py pytest tests/api tests/core tests/worker tests/workflow tests/knowledge tests/agent_runtime tests/composition tests/integrations tests/tool tests/schemas tests/workspace tests/test_core.py tests/test_version.py -q --tb=short
python .cache/atomic4-offline/run.py ruff.exe check app tests cli
python .cache/atomic4-offline/run.py ruff.exe format --check app tests cli
python .cache/atomic4-offline/run.py ty.exe check
```

## Exact changed paths

```text
 M backend/app/db/session.py
 M backend/app/main.py
 M backend/app/services/knowledge/document_service.py
 M backend/app/services/knowledge/document_storage.py
 M backend/app/services/knowledge/embedding/provider.py
 M backend/app/services/knowledge/indexing_service.py
 M backend/app/services/knowledge/retrieval_service.py
 M backend/tests/knowledge/test_document_service.py
 M backend/tests/knowledge/test_document_storage.py
 M backend/tests/knowledge/test_indexing_service.py
 M backend/tests/workflow/application/background/test_executor.py
 M backend/tests/workflow/application/background/test_recovery_scanner.py
 M docs/deploy.md
?? backend/tests/composition/test_resource_disposal.py
?? docs/recovery.md
?? docs/v0.13/atomic5-reliability-recovery.md
```

All changes are local and unstaged. Await ChatGPT Implementation Report Review.

## Supplemental Fix 1 — A5-05 composition disposal (2026-11-27)

The maintainer accepted the primary Atomic 5 report and authorized these four
additional implementation paths. A5-01, A5-03 and A5-04 report reviews passed.
A5-02 remained accepted with this supplemental coverage required. Final Source
Review and Atomic 5 completion remain pending.

The verified initial worktree at main `346bcfd971380c8af7692cf5f74b37b712874550`
and peeled v0.12.0 `6e4cca6bc188d829bc09431080b08ad86e37f3fb` held exactly
the original 13 modified tracked and 3 untracked paths, with empty staging.
SHA-256 was recorded for all 16 paths before edits.

### Finding and correction

Each of the four independent composition entry points created an engine and
then constructed async_sessionmaker before entering the disposal guard.
In the pre-fix synthetic run, each construction failure skipped disposal
(0 calls instead of 1). The targeted reproduction returned exit 1 with
4 failed, 59 deselected and 54 Pydantic warnings. This demonstrates the
missing cleanup path under injection. Live database leakage was not observed.

- `backend/app/composition/workflow_worker.py` (guard and factory at lines 51–58)
- `backend/app/composition/knowledge_index_worker.py` (lines 24–26)
- `backend/app/composition/workflow_recovery.py` (lines 25–27)
- `backend/app/composition/knowledge_index_recovery.py` (lines 24–26)

Engine construction precedes the guard, so a failed construction is propagated
without disposal of an uncreated engine. Once constructed, session factory and
subsequent component creation, entry, body and exit are covered by one disposal
attempt. Workflow tool/MCP context exit precedes engine disposal. A primary
exception or cancellation entering the disposal path is preserved if disposal
also raises. If disposal is the only failure, it propagates. The fixed event
`COMPOSITION_ENGINE_DISPOSE_FAILED` logs without exception text or connection
details. Database settings, NullPool, session options, workflow and knowledge
composition, scanner settings, lifecycle ordering and durability/dispatch
semantics are preserved.

The existing cancellation test was expanded into a parameterized matrix in
`backend/tests/composition/test_resource_disposal.py`. It checks engine
creation, factory and later construction failures, success, body exception,
cancellation and disposal failure, including exception identity, order and
await count. Workflow MCP entry and exit failure cases also verify ordering
and primary error preservation when engine disposal fails. Existing primary
Atomic 5 tests and assertions outside this expansion remain intact.

### Verification

The existing offline launcher injects synthetic Settings and
`AGENTFORGE_ENV_FILE=none` before imports or collection. Exact commands from
the repository root follow (each run supplied a separate result name).

```text
python .cache/atomic4-offline/run.py pytest tests/composition/test_resource_disposal.py -k 'composition_disposal_paths and factory' -q --tb=short
python .cache/atomic4-offline/run.py pytest tests/composition/test_resource_disposal.py -q --tb=short
python .cache/atomic4-offline/run.py pytest tests/workflow/application/background tests/workflow/application/run/test_async_service.py tests/workflow/application/approval/test_service.py tests/workflow/execution/engine/test_recovery.py tests/workflow/persistence/run/repository/test_claim.py tests/knowledge/test_indexing_service.py tests/knowledge/test_index_recovery.py tests/knowledge/test_embedding_provider.py tests/knowledge/test_retrieval_service.py tests/knowledge/test_document_service.py tests/knowledge/test_document_storage.py tests/composition tests/worker tests/api/test_health.py tests/api/test_metrics.py tests/api/test_exceptions.py tests/core/test_operational_observability.py tests/core/test_deployment_contract.py -q --tb=short
python .cache/atomic4-offline/run.py pytest tests/api tests/core tests/worker tests/workflow tests/knowledge tests/agent_runtime tests/composition tests/integrations tests/tool tests/schemas tests/workspace tests/test_core.py tests/test_version.py -q --tb=short
python .cache/atomic4-offline/run.py ruff.exe check app tests cli
python .cache/atomic4-offline/run.py ruff.exe format --check app tests cli
python .cache/atomic4-offline/run.py ty.exe check
```

| Check | Result |
| --- | --- |
| Targeted composition lifecycle file | 63 passed, 54 Pydantic warnings, exit 0 |
| Original focused selection (historically 400 passed) | 434 passed, 54 Pydantic warnings, exit 0 |
| Original broad offline selection (historically 1,335 passed) | 1,369 passed, 150 Pydantic warnings, exit 0 |
| Ruff check | Exit 0 |
| Ruff format check | Exit 0, 512 compliant files |
| ty | Exit 0, two existing workflow warnings |

All three post-fix suites had zero failures and skips. Exactly six paths
received supplemental edits, comprising the four listed composition files,
the existing lifecycle test file and this report. Final cumulative scope is
17 modified tracked plus 3 untracked paths, with no new supplemental path.
The other 14 initial Atomic 5 files match their recorded SHA-256 byte-for-byte.
The primary report text was preserved as an exact byte prefix. Final branch,
HEAD, tag and empty staging were rechecked. Git diff --check and all three
untracked whitespace checks passed.

Disposal remains cooperative. These tests do not measure live resource leakage
or production process shutdown. Real PostgreSQL/Redis/Celery/Provider, Docker,
frontend, paired restore and production recovery verification were NOT RUN.
No protected services or media were used, no Git mutations were performed,
and Atomic 6 was not started. Await ChatGPT Supplemental Fix Report Review.

## Review Fix 1 — RF-01 workflow exception precedence (2026-11-27)

Initial branch `review/v013-atomic5-reliability-recovery` at
`c94f6519cdbf54523a3d974dd27fed5997b18484`. Parent and local main were
`346bcfd971380c8af7692cf5f74b37b712874550`. Peeled v0.12.0 was
`6e4cca6bc188d829bc09431080b08ad86e37f3fb`. The starting worktree and staging
were clean. The supplied Final Source Review decision was CHANGES REQUIRED.
The earlier primary and supplemental results above remain historical evidence.

Reviewed the Workflow worker composition and existing engine-disposal guard,
API lifespan's primary exception handling, Tool Platform and MCP stdio context
entry/exit, and the two composition test files. The old worker guard only saw
the error after MCP exit, which could replace a construction or execution error
or cancellation. The pre-fix synthetic cases returned exit 1 with 5 failed,
1 passed, 63 deselected and 54 existing Pydantic warnings. Each of the five
failures returned the MCP RuntimeError instead of the original ValueError or
CancelledError. Exit ordering and once-only disposal assertions had already
passed in all six cases. The sole MCP exit failure case passed throughout.

The worker now captures the original error inside the successfully entered
Tool Platform scope, including component construction and execution across
the yield. It re-raises inside the scope so MCP still receives the failure
during exit. If MCP exit replaces it, the outer guard logs the fixed
`WORKFLOW_TOOL_PLATFORM_CLEANUP_FAILED` event and re-raises the original
exception object without displaying the cleanup exception chain. The existing
disposal guard runs once after MCP exit and preserves the primary exception.
Sole MCP entry/exit and engine disposal errors propagate. Engine settings,
NullPool, session options, workflow composition and the MCP implementation
are preserved. Neither cleanup diagnostic includes exception text or payloads.

The six new regression cases cover execution, cancellation and construction
after MCP entry with a failing MCP exit, execution and cancellation with both
cleanup operations failing, and an otherwise successful body with a failing
MCP exit. The tests assert exception object identity, MCP exit before exactly
one engine disposal, and fixed diagnostics. Existing successful and independent
failure paths were rerun. Cleanup remains cooperative and does not establish
actual process shutdown.

Exact commands from the root, each using its own launcher result name, follow.
The launcher sets `AGENTFORGE_ENV_FILE=none` and injects synthetic Settings
before backend imports or collection.

```text
python .cache/atomic4-offline/run.py pytest tests/composition/test_resource_disposal.py -k preserves_primary_across_mcp_exit -q --tb=short
python .cache/atomic4-offline/run.py pytest tests/composition/test_resource_disposal.py tests/composition/test_workflow_worker.py -q --tb=short
python .cache/atomic4-offline/run.py pytest tests/workflow/application/background tests/workflow/application/run/test_async_service.py tests/workflow/application/approval/test_service.py tests/workflow/execution/engine/test_recovery.py tests/workflow/persistence/run/repository/test_claim.py tests/knowledge/test_indexing_service.py tests/knowledge/test_index_recovery.py tests/knowledge/test_embedding_provider.py tests/knowledge/test_retrieval_service.py tests/knowledge/test_document_service.py tests/knowledge/test_document_storage.py tests/composition tests/worker tests/api/test_health.py tests/api/test_metrics.py tests/api/test_exceptions.py tests/core/test_operational_observability.py tests/core/test_deployment_contract.py -q --tb=short
python .cache/atomic4-offline/run.py pytest tests/api tests/core tests/worker tests/workflow tests/knowledge tests/agent_runtime tests/composition tests/integrations tests/tool tests/schemas tests/workspace tests/test_core.py tests/test_version.py -q --tb=short
python .cache/atomic4-offline/run.py ruff.exe check app tests cli
python .cache/atomic4-offline/run.py ruff.exe format --check app tests cli
python .cache/atomic4-offline/run.py ty.exe check
git diff --check
```

| Check | Actual result |
| --- | --- |
| Composition lifecycle and Workflow worker files | 72 passed, 54 Pydantic warnings, exit 0 |
| Earlier focused selection | 440 passed, 54 Pydantic warnings, exit 0 |
| Earlier broad offline selection | 1,375 passed, 150 Pydantic warnings, exit 0 |
| Ruff check | Exit 0 |
| Ruff format check | Exit 0, 512 files conform |
| ty check | Exit 0, two existing Workflow warnings |
| Git diff check | Exit 0 |

All three post-fix pytest selections had zero failures and skips. Only
`backend/app/composition/workflow_worker.py`,
`backend/tests/composition/test_resource_disposal.py` and
`docs/v0.13/atomic5-reliability-recovery.md` changed. This section was appended
with the previous report bytes preserved. The final branch, HEAD, parent,
local main and peeled tag match the initial baseline. Staging remains empty.

Real MCP service shutdown, real PostgreSQL/Redis/Celery/Providers, Docker,
frontend, backup/restore and production recovery were NOT RUN. The broad
offline selection still includes its existing synthetic MCP fixtures.
No Git mutations, service operations or Atomic 6 work occurred.
Final Source Review and Atomic 5 completion remain pending. Await ChatGPT
Review Fix 1 Report Review.
