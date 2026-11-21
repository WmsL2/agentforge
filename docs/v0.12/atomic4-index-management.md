# v0.12 Atomic 4 — Index Management

## 1. Baseline and scope

Verified an initially clean worktree on `main`, HEAD `4fbecb1ed322175c40ddc86622db63151a91ad68`. The user supplied Atomic 3 COMPLETE / PR #33 MERGED / Main CI #182 SUCCESS (16/16), 554 frontend unit tests and 26 Foundation Playwright E2E as baseline evidence. Those CI/E2E results are historical baseline evidence, not verification of this uncommitted local change. Version remains 0.11.0.

Implement only Index Status, explicit job submission/rebuild/retry, controlled polling, active generation display, RBAC, scope/auth isolation and safe English/Polish UI. No backend, worker scheduling, provider, database, runtime dependency, version or CI change.

## 2. Component architecture and admission

Existing localized Knowledge Base Detail → Document List → Document Detail Dialog → new `KnowledgeDocumentIndexPanel`.

The panel mounts only in the existing successful latest-metadata branch after document id, workspace_id and knowledge_base_id match. No independent document route, list-wide status prefetch or upload-triggered indexing was added. Failed/unknown parse status remains readable as status/metadata but cannot submit an index job. Existing upload, preview, download and delete business logic remains unchanged.

- `knowledge-document-index-panel.tsx`: scoped UI, submission confirmation, accepted-job tracking and local operation/resource leases.
- `knowledge-index-utils.ts`: known states, 30-second confirmation bound and safe error-code allowlist.
- `use-knowledge.ts`: compatible optional controlled polling on the existing Index Status Hook.
- `knowledge-management.tsx`: Knowledge-only fresh owner/admin write preflight, propagated through existing content/scope props.
- Translation namespace: `knowledgeManagement.documents.index`, matching en/pl keys.

## 3. API and Hook chain

Panel → `useKnowledgeIndexStatus` / `useKnowledgeIndexMutation` → existing `knowledgeApi.getIndexStatus` / `requestIndex` → guarded `apiClient` → existing same-origin `/api/workspaces/{w}/knowledge-bases/{b}/documents/{d}/index` proxy → existing backend.

GET returns 200; POST returns 202 with `KnowledgeIndexJobRead`. No second API client or direct backend call was introduced. Signals, identity snapshots, encoded IDs, workspace-loss checks and exact query prefixes remain those of Atomic 1.

## 4. State machine and authoritative fields

| Latest status | UI/action | Automatic polling |
| --- | --- | --- |
| not_indexed | Build index, if ready and freshly writable | No, except bounded confirmation of an accepted new job |
| pending | Pending; no duplicate submit | Approximately every 3000 ms while valid and foreground |
| running | Running; no duplicate submit | Approximately every 3000 ms while valid and foreground |
| succeeded | Rebuild, requiring explicit cost confirmation | Stops |
| failed | Safe reason; explicit owner/admin Retry | Stops |
| unknown | Unknown; no write action | Stops |

The status response must have the current document_id. Invalid response identity never opens actions or polling. Display uses actual document_id, job_id, status, active_generation_id, chunk_count, embedding_model, index_version and error_code. Known error codes are shown as an allowlisted code plus translated explanation; unknown codes only produce a generic safe explanation.

No percentage, progress bar, completed/total chunks, ETA, fake success, job cancellation, history or chunk-list action is shown.

## 5. Latest job versus active generation

Read the actual `KnowledgeIndexingService.get_index_status`: latest job comes from `get_latest_job_scoped`, active generation from the document, active chunk count from `count_active_chunks`, and model/version from the effective active job when present. These are separate concepts.

The panel separately labels the latest job ID/status and the currently active generation/model/version/chunk count. An active-index claim appears only for a non-null active_generation_id. A failed latest rebuild with an old active generation explicitly says the previous successful index remains active. Running rebuilds likewise retain the actual active information. POST's candidate index_generation_id is never promoted to an active generation by the frontend. Chunk count always describes the active index, never task progress.

## 6. Submission, rebuild and retry

Writes require verified document scope, parse_status=ready, owner/admin membership, a successful matching known status that is neither pending nor running, no outstanding accepted-but-unconfirmed job and no pending local submission. A synchronous lock prevents double submission.

Build and Retry are explicit actions. Rebuild first shows an inline confirmation group inside the existing document dialog, warning that embedding computation may incur costs. Its Cancel only cancels the confirmation; it does not cancel any backend job.

Immediately before POST, `revalidateWrite()` refetches the existing fresh Workspace Membership query and explicitly requires the current user/workspace pair and role owner/admin. A successful ordinary membership `revalidate()` is not treated as write authorization. After permission I/O the panel checks its identity/mount/resource lease and the current scoped Index query again before submitting.

202 means accepted, not completed. Display the actual returned job ID and the state returned with acceptance. An existing active job returned by backend idempotency is handled using that actual ID. The existing mutation invalidates status; the UI never sends a second speculative POST. Ordinary POST failure preserves displayed authoritative status and shows a safe explanation.

The UI and React Query do not automatically retry POST. Existing apiClient may perform its identity-safe retry after a successful authentication refresh; no claim is made that HTTP POST is never resent under any condition. There is no new automatic job rebuild/retry loop.

## 7. Controlled polling and 202 consistency delay

`useKnowledgeIndexStatus` retains its default non-polling behavior for existing callers. Optional controls are `pollActive`, `awaitJob: {id, until}` and a synchronous `isCurrent` resource-lease predicate. The panel opts in. Query identity is checked both when calculating the interval and immediately before the facade call, including authentication generation, not merely user id.

Poll only successful, matching, known status responses. Pending/running use a React Query dynamic refetchInterval of 3000 ms; no global polling service or permanent application interval was added. `refetchIntervalInBackground=false` suppresses background-tab HTTP polling. For the opt-in panel, focus/reconnect does not automatically revive a failed query; Manual Refresh is available. Reopening the document still reads fresh state via existing mount policy.

After 202, a short-lived older GET response must not confirm completion of the accepted job. Track its actual job ID in this keyed panel. If status still reports another job, display that distinction, suppress further writes and check at 3-second intervals for up to 30 seconds. On expiry stop automatic confirmation and instruct the user to refresh manually. A successful response with the accepted ID then follows normal active/terminal polling rules. A query error always stops the interval, including during confirmation.

Polling stops on terminal/not-indexed state without confirmation, unknown or mismatched status, errors, close, scope change, identity transition, document/base deletion or confirmed Workspace loss. Scope clearing invalidates the synchronous resource predicate before React unmount, so even an old scheduled query cannot admit another HTTP request.

## 8. Workspace RBAC boundary

Member may read status but has no build/retry/rebuild button, even if the user's application role is admin. Owner/admin may request writes only after a fresh role-specific preflight. Unknown, failed, missing or loading membership cannot write.

The existing Knowledge Membership refetch normally unmounts its resource subtree. A local `writeCheck` permits the already verified reader to remain mounted during its own preflight, so a successful permission round trip can continue in the same panel. All writes are hidden while the Membership query is fetching. The callback returns true only from fresh success plus exact owner/admin membership. Ordinary read revalidation, initial access gates and default Workspace/Workflow hooks/policies retain their behavior; no global permission system was added.

403 stops local writes/queries and invokes existing document error handling to revalidate membership. Immediate successful revalidation may leave a safe terminal-error dialog instead of unmounting it; it never leaves an enabled write control. 404 invalidates only this document prefix and separately uses the existing base refetch to distinguish base absence. The facade still confirms Workspace loss separately. A single document 404 never clears unrelated Workspaces.

## 9. Scope and authentication isolation

Existing KnowledgeSession generation/epoch and workspace/base/document keys isolate resource lifetimes. `useKnowledgeLease`, guarded facade/mutation operations and AbortSignal reject old identity results. `onKnowledgeClear` synchronously invalidates the panel's resource lease and removes accepted-job/confirmation state; exact document cleanup also cancels Index queries/mutations.

Before/after permission requests and POST, the handler checks the current lease. GET and polling errors are only routed to the current parent. Delayed 202, old status, old 403, stale retry callbacks or old finally handlers cannot close a new dialog, navigate, issue another POST or show an old result. No panel toast or navigation was added. Scope callbacks are not a new global authentication framework.

Stopping local polling/request observation does not cancel a server-accepted job. The backend remains the final authorization and idempotency boundary.

## 10. Safe error mapping and source review

Read `backend/app/services/knowledge/indexing_service.py`, `embedding/provider.py`, the existing Index proxy, types and Hooks before implementation. The translated allowlist comes from actual sources:

- Service/worker: DOCUMENT_NOT_READY_FOR_INDEXING, DOCUMENT_CONTENT_CHANGED, DOCUMENT_HAS_NO_INDEXABLE_TEXT, DOCUMENT_CHUNK_LIMIT_EXCEEDED, EMBEDDING_CONFIGURATION_MISMATCH, KNOWLEDGE_INDEX_INTERNAL_ERROR.
- Provider/configuration/response validation: EMBEDDING_RATE_LIMITED, EMBEDDING_TIMEOUT, EMBEDDING_PROVIDER_UNAVAILABLE, EMBEDDING_API_KEY_MISSING, EMBEDDING_DIMENSIONS_INCOMPATIBLE, EMBEDDING_CONFIGURATION_INVALID, EMBEDDING_MODEL_MISMATCH, EMBEDDING_PROVIDER_REJECTED, EMBEDDING_COUNT_MISMATCH, EMBEDDING_DIMENSION_MISMATCH, EMBEDDING_VALUE_INVALID, EMBEDDING_ZERO_VECTOR.

Unknown codes use a generic safe indexing message. Existing safe HTTP mapping handles 401/403/404/409/422 and generic network/5xx failures; the existing authentication mechanism handles 401. Never render raw backend/provider detail, credentials, private URLs, stack traces or internal paths. Aborted/invalidated operations have no stale UI side effects. Failed jobs are retried only by explicit authorized action.

## 11. Tests

New tests use real QueryClient, Knowledge Hooks, Auth Store and API facade with HTTP-boundary responses/delays. Polling uses fake timers and controlled focus state, not real 3-second waits. Coverage includes all five states plus unknown, query loading/error/manual refresh, scope mismatch, latest-versus-active generation, no fake percentage, roles and parse readiness, permission preflight/downgrade, rebuild consent, 202 acceptance/duplicate lock/existing job, bounded stale confirmation, invalid job responses, safe real error codes, foreground polling and terminal/error stop, default Hook compatibility, close/scope/auth switches, delayed GET/POST/permission/poll errors, exact cache cleanup, StrictMode effect replay and synchronous resource admission.

Original 554 tests are preserved. Atomic 3's 104-test HTTP fixture adds a matching not_indexed response for the newly mounted GET Index status; no old assertion is removed or skipped. Existing upload tests still verify that upload does not automatically call Index. Old Knowledge Base, Workspace/Workflow, authentication race, multipart and binary proxy/API tests remain in the full suite. Coverage configuration/thresholds remain unchanged.

Final executed verification is recorded in section 13.

## 12. Known limitations and deferred features

- Linux Node 24 and real browser/backend/worker integration are not executed for this local diff. Docker Desktop remains user-closed; no start/resume, containers, WSL environment or backend/PostgreSQL/Redis/Celery services were started. Atomic 2's temporary container was not modified or removed. Await later GitHub CI/integration validation.
- No real provider API or paid embedding smoke call was performed. HTTP-boundary frontend evidence does not prove job execution, database state, broker delivery or provider availability.
- No live browser visual/mobile test or Foundation Playwright E2E was run for this diff. Baseline 26 E2E is historical only.
- The 30-second bound applies to confirming an accepted job ID, not to job execution time. Slow status consistency or a newer job superseding that accepted ID can leave confirmation unresolved; refresh manually or reopen for fresh authoritative latest status. The UI cannot infer a completed historical job without an API for it.
- Membership is revalidated through existing requests, not pushed in real time. Backend authorization remains decisive. Already accepted jobs continue when a dialog closes or the client disconnects.
- No Index cancel/delete/history/chunk API, progress percentage, search/ask, Workflow Knowledge Node, new provider/chunking algorithm, migration, runtime dependency or version update. Atomic 5 was not started.


## 13. Executed final verification

Windows Node v22.13.0, Bun 1.3.14, Next.js 15.5.23. All results below were executed on the final implementation; local logs are ignored and are not committed.

| Check | Actual result |
| --- | --- |
| `bun install --frozen-lockfile` | PASS, exit 0; 839 installs / 950 packages checked, no changes. Existing Husky prepare reports `.git can’t be found`. |
| `bun run lint` | PASS, exit 0; 0 errors / 13 existing warnings, no new Index code warnings. |
| `bun run type-check` | PASS, exit 0. |
| `bun run test:run` | PASS, 647 tests / 30 files: original 554 + 93 new Index tests, no skipped tests. |
| `bun run test:coverage` | PASS, 647 tests / 30 files, original include list and thresholds unchanged. |
| `bun run build` | PASS, exit 0. Existing runtime-config deprecation and unrelated accessibility warnings remain. |
| `bun run test:run -- src/components/knowledge/knowledge-document-index-panel.test.tsx` | PASS, 93 tests / 1 file. |
| Existing Knowledge UI regression before final full suite | PASS, 189 tests, including Atomic 3's 104 document tests. |
| `git diff --check` | PASS. |
| Linux Node 24 / real browser-backend-worker integration / Foundation Playwright / provider smoke | NOT RUN for this local diff. |

Coverage remains the existing four files: auth-cookies.ts, utils.ts, auth-store.ts, button.tsx. Aggregate statements/lines 69.23%, branches 100%, functions 60.86%; these are not new Index-panel coverage percentages. Thresholds remain 50/90/40/50 respectively for statements/branches/functions/lines. No tests, assertions or coverage policy were removed or weakened.

Logs: `frontend/node_modules/.cache/atomic4-{target,regression,lint,type-check,test-run,test-coverage,build}.log`.

## 14. File and Git accounting

New (4): Index panel, Index utilities, Index component test file, this document.

Modified (9): en/pl message files; KnowledgeManagement owner/admin preflight; KnowledgeBaseList content-prop type; KnowledgeBaseDetail prop forwarding; DocumentScope type; Document Detail panel integration; existing Document test HTTP fixture (one GET status response only); existing use-knowledge Index Status Hook optional polling controls.

No backend, authentication coordinator, Workspace/Workflow default hook implementation, migration, dependency/lockfile, CI configuration or version file was modified. Default Index Status Hook remains non-polling. Existing document upload/preview/download/delete business logic was not changed.

Final branch `main`, HEAD `4fbecb1ed322175c40ddc86622db63151a91ad68`, unchanged from baseline. Nine tracked modifications and four untracked new files remain local and unstaged. No branch creation/switch, git add/commit/push/merge/reset/stash, PR/tag/release or Atomic 5 action occurred. Awaiting ChatGPT review.
