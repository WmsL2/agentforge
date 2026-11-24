# v0.12 Atomic 7 — Execution Result Integration

Sections 1–14 record the original implementation and its historical validation. Review Fix 1 and Review Fix 2 below record successive review corrections; the latest section supersedes earlier lifecycle and Git accounting where applicable. Final Source Review remains pending ChatGPT review.

## 1. Baseline verification

Started from clean `main`, exact HEAD `b05aad53e432d493bc1871d59c7679c8893b206d`. Initial status and diff whitespace checks passed. Atomic 6 / PR #36 is the merged baseline, with 850 frontend tests / 33 files and 26 historical Playwright tests. Version remains 0.11.0.

Read-only GitHub Actions lookup confirmed [Main CI #188](https://github.com/WmsL2/agentforge/actions/runs/45171634916), event push, branch main, exact baseline SHA, completed/success. The supplied baseline reports 16/16 jobs; individual jobs were not queried in this turn. Baseline CI is not evidence for this uncommitted Atomic 7 change.

## 2. Source review

Re-read execution panel and tests, WorkflowDetail, workflow-run hooks/tests, Workflow API, workflow wire types, query keys, Knowledge Playground and helpers, auth identity and en/pl execution messages. Read backend run routes, run/observability schemas, Knowledge executor, Agent executor and Knowledge composition without modification. Consulted v0.11 Knowledge Node / Agent Tool and v0.12 Atomic 5/6 documents.

The existing v0.11 runtime already retrieves evidence and composes Knowledge Agent tools. This Atomic only explains persisted execution output in the existing frontend panel. It adds no executor, API, provider call, background work or run status.

## 3. Runtime data contracts

Run detail supplies id, workflow_id, workflow_revision and definition_snapshot. RunStep supplies its own id, run_id, sequence, node_id, node_kind, status and output. Trace is a separate event stream and is never an evidence source for the new renderer.

Knowledge output requires a string query, nonnegative safe integer total and results array. Each match requires string chunk_id/document_id/filename/content, nullable integer page_start/page_end and finite numeric similarity_score. Agent output requires string answer, status answered/no_evidence and sources with the same metadata except content. no_evidence requires empty sources. Unknown/missing/wrong-typed values fail closed. Nullable pages are shown as a dash. Zero and negative similarity scores are retained, without conversion to percentages or confidence.

## 4. Knowledge retrieval UI

WorkflowKnowledgeResults appears beside each step's original JSON output, preserving title, sequence, status, timestamps and duration. It shows the actual query, total, returned item count, filename, IDs, content, page bounds and similarity score in backend order. It does not invent embedding model, chunk index, offsets, base ID, URLs, preview/download links or index state.

An empty array is a normal completed retrieval result. Unexecuted, running, failed or interrupted steps do not acquire an empty-evidence message. A completed null/malformed output produces a safe interpretation warning while raw JSON remains available.

## 5. Agent answer and sources

Only snapshot-confirmed Agent knowledge bindings use the Agent renderer. answered displays the actual answer and actual sources; empty sources receive an explicit message. The answer is never parsed to infer citations. no_evidence uses a localized explanation of insufficient supporting evidence without implying document absence, index failure or run failure. Its backend message remains available in raw JSON.

Ordinary Agent output remains in the existing JSON viewer. Unknown status, malformed sources or inconsistent no_evidence are not reclassified as answered or empty retrieval.

## 6. Definition snapshot boundary

The parser accepts only completed Knowledge/Agent steps. It exactly matches selected Run ID, Run.workflow_id, Step.run_id, nonempty Step.node_id and Step.node_kind. The selected run snapshot must contain exactly one matching node of the same kind. Agent config must contain a valid UUID knowledge_base_id; absent binding means ordinary Agent, invalid binding means unavailable interpretation.

Current Workflow.definition, canvas selection/coordinates and Trace payload are not inputs to interpretation. Tests switch between r3/r4 with opposite Agent bindings and change the current canvas in both directions. Repeated steps for the same node retain their distinct step IDs and actual sequence; no node_id deduplication or sorting is introduced.

## 7. Run, Step and Trace distinction

Run status and Step status remain independent. Completed earlier steps can be examined even if the overall Run later fails. Missing steps mean no recorded steps, not inferred execution failure. Trace errors do not turn valid Step output into empty evidence. Existing run submission/history/polling, step/trace views, approval/rejection, refresh, revision and JSON-copy behavior remain.

## 8. Components and query lifecycle

- lib/workflow/knowledge-run-results.ts: pure snapshot/output validation, result union and bounded Unicode text helper.
- components/workflow/workflow-knowledge-results.tsx: shared metadata display, retrieval/Agent results and safe states.
- workflow-execution-panel.tsx: small integration and keyed execution session; existing hooks/facade are unchanged.

Structured results require successful, fetched-after-mount Run and Steps queries with neither fetching. Cached data during initial read, refetch or error cannot serve as a verified structured result. Existing query keys and Refresh/polling are reused; intervals remain unchanged. Raw JSON remains the existing debug view and does not claim that stale or malformed output has passed interpretation.

## 9. Authentication and scope isolation

Execution session keys include supplied user, workspace, workflow, existing auth generation and transition epoch. Full auth-state subscription observes batched logout/relogin even when the final user object reference is unchanged. Scope changes clear local selection and prevent old submissions/approvals from updating the new session through the existing mounted-request guard. Structured rendering also requires current authenticated identity to match the supplied user.

Existing authenticated parent admission, API identity protection, user/workflow/run query keys and backend RUN_READ authorization remain authoritative. Run DTO has no workspace_id; frontend does not invent one. Workspace interpretation is tied to the supplied workflow scope and its protected API response, not inferred from output data. No Auth Store, identity coordinator or global RBAC changes were made.

## 10. Safe rendering and errors

All query, filename, IDs, content and answer text use ordinary React text nodes in scrolling containers. Each displayed external text is limited to 10,000 Unicode code points with an explicit truncation notice, retaining full values in the existing JSON viewer. No HTML/Markdown execution, remote image fetch, URL navigation, citation parsing or unauthenticated file link is introduced. This cap limits rendering, not network payload or all in-memory data.

HTTP error display uses translated fallback/403/404 messages instead of private API detail/message. Known dispatch failure and approval conflict map to fixed localized messages, preserving existing behavior/tests without reflecting arbitrary messages. Existing structured submission-validation issues and persisted runtime diagnostics remain under the original JSON/diagnostic boundary. The new renderer never displays provider errors as evidence.

New strings are under workflows.execution.knowledgeResults, with two safe execution-error strings alongside it. en/pl key parity is tested. No global navigation changes.

## 11. Test coverage and verification

New tests use three files: pure contract tests, result component tests and HTTP-boundary execution integration tests. Integration uses the real panel, QueryClient, workflow-run hooks, facade, apiClient and Auth Store, mocking only fetch. Coverage includes malformed fields, zero/negative similarity, empty output, ordinary/bound Agent distinction, HTML/Unicode bounds, snapshot mismatches, repeated attempts, r3/r4 binding changes, cached/loading/refetching queries, delayed responses, user/workspace/workflow/logout/same-user transitions and independent API errors. Existing execution tests are retained unchanged.

Executed on Windows, 2026-11-23, Node v22.13.0 / Bun 1.3.14 / Next.js 15.5.23:

| Command/check | Actual result |
| --- | --- |
| `bun install --frozen-lockfile` | PASS, exit 0; 839 installs across 950 packages, no changes. Existing Husky `.git can't be found` message is nonfatal. |
| `bun run lint` | PASS, exit 0; 0 errors / 13 existing warnings. |
| `bun run type-check` | PASS, exit 0. |
| `bun run test:run` | PASS, 947 tests / 36 files: original 850 plus 97 new, no skips. |
| `bun run test:coverage` | PASS, 947 tests / 36 files. |
| `bun run build` | PASS, exit 0; existing runtime-config deprecation and unrelated lint warnings remain. |
| Final targeted regression | PASS, 265 tests / 7 files, including all 97 new tests and unchanged execution-panel (40), use-workflow-runs (2), workflow-detail (3), Knowledge Playground (123). |
| `git diff --check` and separate new-file whitespace check | PASS. |
| Linux Node 24 / Playwright / real Backend E2E / paid Provider | NOT RUN. |

New test counts: knowledge-run-results.test.ts 59, workflow-knowledge-results.test.tsx 17, workflow-knowledge-execution.test.tsx 21. The final targeted command was `bun run test:run -- src/lib/workflow/knowledge-run-results.test.ts src/components/workflow/workflow-knowledge-results.test.tsx src/components/workflow/workflow-knowledge-execution.test.tsx src/components/workflow/workflow-execution-panel.test.tsx src/hooks/use-workflow-runs.test.ts src/components/workflow/workflow-detail.test.tsx src/components/knowledge/knowledge-playground.test.tsx`.

Coverage policy remains restricted to auth-cookies.ts, utils.ts, auth-store.ts and button.tsx: aggregate statements/lines 69.23%, branches 100%, functions 60.86%. These do not measure the new results UI. Original thresholds remain statements 50, branches 90, functions 40, lines 50. No existing test file, coverage include or threshold was modified.

Local ignored logs: frontend/node_modules/.cache/atomic7-{target,regression,lint,type-check,test-run,test-coverage,build,install}.log.

## 12. Known limitations

Windows tests validate frontend interpretation at mocked HTTP boundaries. They do not prove real retrieval quality, grounding, DB/checkpoint/worker state, provider availability or backend execution. Linux Node 24, local Playwright, real Backend E2E, browser visual/mobile validation and paid LLM/Embedding calls are NOT RUN. Historical 26 Playwright tests and baseline CI are not claimed as this change's validation.

The UI does not independently authenticate citations or reauthorize each source against a live knowledge base; it displays actual protected persisted output. Current server authorization remains decisive. No new realtime revocation mechanism or backend cache system is introduced.

## 13. Deferred features

No Atomic 8. No Backend Knowledge retrieval, Agent runtime, Tool Platform, Workflow engine/checkpoint/recorder changes, database/migrations, new APIs/statuses, schema/version/dependency/lockfile/CI changes, automatic retry/execution, streaming, cost/token estimates or document previews/downloads.

## 14. Git and service restrictions

All changes remain local and unstaged on main at the exact baseline HEAD. No branch creation/switch, git add/commit/push/merge/reset/stash/rebase, PR/tag/release. Docker/containers and Atomic 2 leftovers were not operated; WSL, Backend, PostgreSQL, Redis and Celery were not started. Awaiting ChatGPT Implementation Report Review.

Final file accounting: 3 tracked modifications (execution panel and en/pl translations), 6 untracked additions (result parser/component, three test files and this document). Staged diff is empty. Hooks, API facade, auth identity/store, WorkflowDetail, current editor, backend and existing tests remain unchanged.

## 15. Review Fix 1 — 2026-11-24

### Baseline and reproduction

Initial worktree was clean on `review/v012-atomic7-execution-result-integration`, exact HEAD `201e5bb921b0f59434f9e94ec0fb562640a7987b`. Initial diff whitespace check passed. PR #37 is the supplied open review context; this fix does not declare Final Source Review PASS.

The production Providers config uses staleTime `5 * 60 * 1000` and gcTime `30 * 60 * 1000`. The original integration fixture used React Query's default staleTime=0 and therefore missed the production interaction. After changing the test defaults to production values, two new focused remount/A→B→A tests failed against the original implementation: 2 matched tests failed; the other 21 tests were not selected by the name filter. No test was disabled or removed. Reproduction log: `frontend/node_modules/.cache/atomic7-fix1-repro.log`.

### Production Cache Compatibility

`isFetchedAfterMount` correctly prevents interpreting a cached result as a fresh read, but the five-minute fresh cache could prevent the required read from starting. The guard remains. History/Detail/Steps/Trace read hooks now explicitly use local staleTime=0 and refetchOnMount="always", so a mount or history selection revalidates automatically even under the unchanged global production defaults. QueryClient still retains its configured cache and gcTime. No global staleTime, Providers code or polling interval changed: active 3000ms, paused 10000ms, terminal false. No per-render refetch effect or repeating request loop was added. Remount/A→B→A tests assert the expected request counts.

### Authentication Request Isolation and Query Cancellation

The original component key isolated local React state only. Existing query keys could share both successful data and an in-flight promise across a same-user login, and the facade did not pass signal/identityGuard for these reads.

New local `workflow-run-lifecycle.ts` appends the existing Auth Identity generation and transitionEpoch to each read key while keeping the original resource prefix intact for invalidation. New sessions cannot share an old flight or reuse its cached response as permission verification. This is scoped to execution reads; the global query-key catalog and global QueryClient are unchanged. Historical entries can remain until their existing gcTime expires, but are not selectable by the new session's keys.

Every History/Detail/Steps/Trace query subscribes to the existing auth state and verifies that the authenticated user matches its requested user. The query function captures the identity represented by its key, consumes React Query's AbortSignal, forwards an AbortController signal and identityGuard through Workflow API to apiClient, and checks identity again before returning. A local synchronous auth subscription aborts active transports when identity becomes invalid; QueryClient cancellation and observer unmount also reach the signal. Abort failures are not retried. Ordinary GET failures retain one retry. Even a mocked transport that ignores abort cannot commit a late response after the identity check.

Run details seeded after submission are written under the originating session key. Existing prefix invalidation still refreshes current execution queries. Submission/approval POSTs, approval cache/read behavior, permissions and mutation retry policy were not rewritten; no automatic POST retry was added. No Auth Store, Auth Coordinator, apiClient, Knowledge Lifecycle or backend RBAC change.

### Raw JSON Scope Protection

An unauthenticated/request-user mismatch does not mount the execution session. Run/Workflow mismatch continues to hide associated results. Foreign RunStep input/output and foreign TraceEvent payload are replaced by the existing safe unavailable message; their protected JSON is never rendered.

An explicit 403/404 from any of the four execution reads blocks the selected run's cached bodies and structured results, including during a pending retry. Fresh successful authorization can restore them. Denied history rows are hidden. Ordinary same-session background refetch can retain diagnostic JSON while structured output is unverified. Valid current-session malformed output and ordinary Agent JSON remain reviewable. Step/Trace errors do not masquerade as retrieval emptiness.

### Additional Regression Tests and Fixture Changes

All original 947 tests remain, with no assertion removed, weakened or skipped. Added 21 tests: 17 execution HTTP-boundary regressions and 4 real-hook lifecycle tests. They cover production fresh-cache remount and A→B→A, cached pending/success/failed revalidation, same-user logout/relogin followed immediately by the same Run, independent new-session Detail and Steps requests before old responses finish, synchronous old-signal cancellation, no late cache/UI adoption, mismatched request user, foreign Step/Trace raw JSON, cached 403/404 for each of History/Detail/Steps/Trace, denial during retry and successful recovery, explicit QueryClient cancellation, transitionEpoch key isolation, and identity loss while consuming an HTTP body.

The tests use real QueryClient/Hooks/facade/apiClient/Auth Store and mocked HTTP responses; logout/relogin transitions use the existing Auth Store API. They do not claim real cookie-handler/backend authentication integration.

Two existing fixture adjustments were necessary to represent the real protocol: (1) the 40-test mocked execution-panel suite now establishes authenticated user-1, matching the panel's supplied user, instead of relying on an unauthenticated panel; every original assertion is unchanged. (2) existing HTTP integration cache seeds now use the auth-session read key, and their QueryClient defaults match production five-minute freshness/thirty-minute retention. Original integration assertions remain intact. The existing current-session cache freshness test now exercises actual seeded session data rather than an unused bare resource key.

### Actual Verification Results

Windows, Node v22.13.0 / Bun 1.3.14. Final commands executed after code/test changes:

| Command/check | Actual result |
| --- | --- |
| Lifecycle and related targeted regression | PASS, 286 tests / 8 files. |
| `bun run lint` | PASS, exit 0; 0 errors / 13 existing warnings. |
| `bun run type-check` | PASS, exit 0. |
| `bun run test:run` | PASS, 968 tests / 37 files; original 947 plus 21 new, no skips. |
| `bun run test:coverage` | PASS, 968 tests / 37 files. |
| `bun run build` | PASS, exit 0; existing runtime-config deprecation and unrelated lint warnings remain. |
| `git diff --check` and separate new-file whitespace checks | PASS. |
| Linux Node 24 / Playwright / real Backend E2E / real Provider | NOT RUN. |

Targeted files: workflow-knowledge-execution (38), workflow-execution-panel (40), use-workflow-runs (2), new use-workflow-run-lifecycle (4), knowledge-run-results (59), workflow-knowledge-results (17), workflow-detail (3), knowledge-playground (123). Logs: `frontend/node_modules/.cache/atomic7-fix1-{repro,target,regression,lint,type-check,test-run,test-coverage,build}.log`.

Coverage includes and thresholds remain unchanged; aggregate statements/lines 69.23%, branches 100%, functions 60.86% still refer to the original four-file scope, not the new lifecycle/UI. No dependencies, lockfiles, CI, version or schema changes.

### Git and remaining limitations

Current fix changes six tracked files (this document, execution panel, its mocked test fixture, execution integration tests, run hooks and Workflow API), and adds two files (execution lifecycle helper and real-hook tests). All changes are local and unstaged; branch/HEAD remain the exact review baseline. No branch creation/switch, add/commit/push/merge/reset/stash/rebase, PR/tag/release or Atomic 8 action occurred. Docker, containers, WSL, Backend and real Providers were not started or used. Local passing checks are not Final Source Review approval; awaiting ChatGPT Review.

## 16. Review Fix 2 — Authorization Denial Persistence

### Baseline and root cause

Initial checks confirmed a clean `fix/v012-atomic7-query-lifecycle` at exact HEAD `fa63d2a5c15a8b840df17027dc4161bf3186bcae`. PR #38 / CI #191 / 968 frontend tests and 26 Playwright tests are supplied baseline context, not new local verification.

Before production changes, eight real HTTP-boundary regressions reproduced the issue for History, Detail, Steps and Trace: 200 → 403 → 503, and 200 → 404 → network failure. All eight failed because cached protected JSON reappeared. The other 38 integration tests were outside the reproduction name filter, not disabled. Reproduction log: `frontend/node_modules/.cache/atomic7-fix2-repro.log`.

React Query retains old data after a failed refetch. The panel previously derived access denial solely from the latest query error, so a transient error could overwrite a confirmed 403/404. Detail/Steps freshness checks could still block structured interpretation, while cached JSON reappeared; History/Trace failures could also lift the combined structured-result block.

### Authorization denial persistence and recovery

Each execution read now has a local cache-only denial record under its unchanged session/resource read key plus `authorization-denied`. It has a disabled observer and makes no HTTP request. A record initialized to false means no confirmed denial is recorded; it does not verify any cached response or replace the existing freshness guards.

The shared guarded request records true only for an identity-current 403/404. It clears only that exact resource's record after a fresh successful HTTP read passes the existing AbortSignal/identity checks. Pending, cancellation, 500/503, network failures and another resource's success leave the record unchanged. Late successful responses from cancelled requests cannot clear it. Mutation cache seeds, ordinary rerenders and remounts do not clear it.

The panel reads these persistent flags in addition to its existing mismatch/error checks, preserving the protection of selected structured results and raw JSON. History rows also respect the History denial flag. Run-scoped records remain associated with the denied Run through A → B → A and do not block a different legitimate Run. History records follow their existing workflow/pagination resource key. User/generation/transitionEpoch key isolation remains unchanged, so a new authenticated session cannot inherit another session's denial or authorize its data.

The denial record uses the existing QueryClient retention defaults and remains observed alongside its read. Clearing the whole cache removes the protected data too; this fix introduces no new global QueryClient configuration or permanent global map. Existing session keys, polling intervals, local freshness policy, transport guards, ordinary Agent handling and legal JSON diagnostics are retained. No backend or global authentication change.

### Retry policy

History/Detail/Steps/Trace now share an explicit retry predicate: 403/404 and AbortError receive no automatic retry; temporary HTTP/network errors retain the previous single retry. HTTP tests assert one denial request and two transient-failure attempts. Submission/approval mutation behavior is unchanged.

### Regression tests

Added 21 tests: eight denial → transient-failure cases, four per-resource pending/other-success/cancellation/fresh-success cases, three Run A → B → A cases, two user/session-isolation cases and four retry-policy cases. Tests check both structured results and protected raw bodies, using the existing real hooks/facade/apiClient/Auth Store and production five-minute/thirty-minute QueryClient defaults with mocked HTTP.

The original 968 tests remain. The cancellation test now explicitly identifies all four original protected-data queries and retains the no-data-adoption assertion for each; it additionally checks four cache-only denial records remain false. This distinguishes new boolean metadata from protected HTTP response data without weakening the original cancellation assertion. No existing test was deleted or disabled.

Final targeted execution-panel/lifecycle regression: PASS, 105 tests / 4 files (execution integration 55, execution panel 40, real-hook lifecycle 8, polling/query-key tests 2). Logs use `frontend/node_modules/.cache/atomic7-fix2-{repro,target,lint,type-check,test-run,test-coverage,build}.log`.

### Actual verification results — 2026-11-24

Windows, Node v22.13.0 / Bun 1.3.14. All commands completed against the final code/test changes:

| Command/check | Actual result |
| --- | --- |
| Execution-panel and lifecycle targeted regression | PASS, 105 tests / 4 files. |
| `bun run lint` | PASS, exit 0; 0 errors / 13 existing warnings. |
| `bun run type-check` | PASS, exit 0. |
| `bun run test:run` | PASS, 989 tests / 37 files; original 968 plus 21 new, no skips. |
| `bun run test:coverage` | PASS, 989 tests / 37 files. |
| `bun run build` | PASS, exit 0; existing runtime-config deprecation and unrelated warnings remain. |
| `git diff --check` / changed-file whitespace check | PASS. |

Coverage configuration and thresholds remain unchanged. Aggregate statements/lines 69.23%, branches 100%, functions 60.86% still describe the original four included files, not coverage of this authorization state/UI. No dependency, lockfile, CI, schema or version change.

### Git boundaries and limitations

Only this document, execution panel, run hooks, local run lifecycle helper and their two lifecycle/integration test files change (six tracked files, no new files). All work remains unstaged on the exact review-fix branch/HEAD. No branch creation/switch, add/commit/push/merge/reset/stash/rebase, PR/tag/release or Atomic 8. No Docker, WSL, Backend or real Provider was started. Linux Node 24, local Playwright, real Backend/Provider/auth-cookie-handler integration and browser visual verification are NOT RUN. Passing local tests do not constitute Final Source Review approval; awaiting ChatGPT review.
