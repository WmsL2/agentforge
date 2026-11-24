# v0.12 Atomic 7 — Execution Result Integration

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
