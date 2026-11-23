# v0.12 Atomic 5 — Retrieval & Knowledge Playground

## 1. Baseline and modification gate

Initial worktree was clean, branch `main`, HEAD `95297feebe9ca2319c125db3489dabea3cdd046c`; initial `git diff --check` passed. Version remains 0.11.0. Baseline is Atomic 4 / merged PR #34, 647 frontend tests.

Before any code modification, verified [Main CI #184](https://github.com/WmsL2/agentforge/actions/runs/44914885033) through the GitHub connector's read-only Actions REST resource. Run id 44914885033, event push, head_branch main, exact baseline head_sha, status completed, conclusion success. Queried all jobs with per_page=100: total_count=16, every job completed/success. This satisfied the user's mandatory gate. PR CI #183 SUCCESS is supplied baseline context; this turn independently verified Main CI #184. Those baseline CI results do not validate this uncommitted Atomic 5 diff.

## 2. Actual source review

Read the actual Search/Ask routes (`knowledge_search.py`, `knowledge_agent.py`), `retrieval_service.py`, `agent_service.py`, `agent_tool.py`, relevant Knowledge schemas and embedding provider errors. Frontend review covered the Knowledge API facade, shared useOperation and Search/Ask Hooks, wire types, KnowledgeBaseDetail/KnowledgeManagement, UI leases, scope lifecycle and error classifier.

The existing v0.11 backend handles retrieval authorization, embedding, active-index compatibility, Agent execution, evidence collection and sources. Search authorizes before embedding and rechecks before returning chunks. Ask is a stateless single-request service; its bound tool captures trusted workspace/base/user identity and the backend supplies sources from collected evidence. This Atomic implements only the frontend playground, not another retrieval or Agent execution architecture.

## 3. Components and admission

Existing Knowledge Base Detail successful branch → new keyed `KnowledgePlayground` → Search or Ask panel. Key includes user, Workspace and Knowledge Base; the existing parent additionally keys the authentication generation/epoch. Initial user, fresh Workspace/Membership and matching latest Base metadata gates must all pass before Playground mounts.

- `knowledge-playground.tsx`: root Tabs, separate draft states, private KnowledgeSearchPanel / KnowledgeAskPanel, local UI request lease, evidence rendering and bounded plain text.
- `knowledge-playground-utils.ts`: input normalization/validation and safe error allowlist.
- `knowledge-playground.test.tsx`: real QueryClient/Hooks/Auth Store/API facade with HTTP-boundary delays.
- No global route, navigation, runtime dependency or model setting was added. Existing Document and Index management remain present and unchanged.

Search query/top/minimum and Ask question have separate drafts. Mode changes unmount the inactive operation, cancel it and discard its result/error. Returning to a mode retains its draft within the same scope, but does not resurrect a previous response. Scope/auth changes discard all drafts and responses.

## 4. Search call chain and validation

Explicit form submit or manual Retry → `useKnowledgeSearch(userId, workspaceId, knowledgeBaseId).mutateAsync({query, top_k, min_score})` → existing knowledgeApi.search → guarded apiClient → same-origin Search proxy → existing v0.11 retrieval service. No search-on-type or request on initial mount.

Normalize leading/trailing whitespace using Python-compatible str.strip whitespace, including U+0085 and U+001C..001F while retaining FEFF, then count Unicode code points with Array.from. Query/question length is 1–2000 after normalization. No native UTF-16 maxlength incorrectly rejects 2000 emoji.

Top K defaults to 5 and requires an ASCII digit integer string producing a safe integer from 1 through 20; decimal/fraction/exponent/NaN/Infinity/hex/empty values are rejected. Minimum similarity is optional: blank → null, otherwise a finite decimal/scientific number from -1 through 1. Zero is explicitly valid. Invalid input stops before Membership preflight or POST.

## 5. Search results

Render actual response query and embedding model, and the number of scoped results displayed. Preserve backend order without sorting by similarity. Rows from a different knowledge_base_id are omitted and a scope error is shown; they are not interpreted as authorized results. Display actual filename, document/chunk IDs, chunk index, content, similarity, page start/end and offsets. Null page values show a dash.

Similarity is explicitly a retrieval score, not answer accuracy or confidence. Empty results are a normal outcome; guidance says text may not match and suggests checking indexing, without asserting that no indexes exist. Empty results never create Index jobs.

Retrieved text and answers use a scrollable inert pre element with a 10,000-code-point display cap. Conversion processes only a bounded prefix; the partial-display notice explicitly says the server returned more text. The API still transfers the full response; this is a rendering limit, not server-side content pagination. Filename and metadata are ordinary React text, with no HTML execution, Markdown renderer, iframe, automatic image fetch or synthesized file URL.

## 6. Ask call chain and response

Explicit submit/manual Retry → existing `useKnowledgeAsk(...).mutateAsync({question})` → knowledgeApi.ask → guarded same-origin Ask proxy → existing v0.11 Knowledge Agent service. Only the normalized question is sent, with no prior turn, sources from another request, model override or prompt settings.

- answered: show actual backend answer and actual sources.
- no_evidence: successful localized evidence-insufficient state, not an HTTP error. No answer or citation is invented.
- unknown response status: safe unavailable-response message, without assuming answered.

Sources show only actual chunk_id, document_id, filename, page_start/page_end and similarity_score. An answered response with no sources explicitly says none were returned. Answer text is never parsed to infer citations, and no file links are generated. The source DTO does not include a base ID; its authority comes from the authenticated, scoped request and backend evidence collector, not frontend inference.

No persistent chat, multi-turn memory, history database, streaming/SSE, simulated token output, frontend LangGraph, model selector, prompt editor or temperature control exists.

## 7. Read RBAC and fresh submission permission

Search and Ask use KNOWLEDGE_READ despite being POST. Owner, admin and member may all submit; application-global admin is not a substitute for Workspace membership. No use of canWrite or owner/admin write preflight authorizes these operations.

A minimal optional `revalidateRead` callback is propagated through existing content props. KnowledgeWorkspace refetches its existing fresh Membership query and requires exact current user/workspace membership in owner/admin/member. A locally scoped promise coalesces simultaneous read preflights. The existing action-preflight ref keeps the already verified reader mounted while fetching; writes stay hidden during Membership fetching. Missing/error/revoked membership fails closed, and no Search/Ask POST follows an invalid preflight. Existing owner/admin Index checks and ordinary Workspace/Workflow query defaults remain unchanged.

The backend still performs final authorization. This extra UI preflight does not replace it or establish a global authentication framework.

## 8. Latest-wins, cancellation and scope isolation

Reuse existing Search/Ask useOperation latest-wins, AbortSignal, authIdentity/sameAuthIdentity and qk.knowledge.base keys. Local UI sequencing covers the permission round trip before the mutation starts: identical pending normalized submissions coalesce; a different submission cancels the prior operation immediately and only the latest intent continues after permission validation. A stale finally cannot clear a new request's loading state.

`useKnowledgeLease` checks mount/identity. `onKnowledgeClear` invalidates the resource lease synchronously, clears drafts/results and blocks future operation admission before React unmount. Existing clearKnowledgeScope and registered client lifecycle handle user/workspace/base cleanup. No Blob, query, answer or source is added to persistent storage.

Cancel invokes the existing mutation cancel mechanism. Mode switches unmount/cancel their operation. Account/logout/same-user re-login, Workspace/Base changes, Base deletion and confirmed access revocation isolate old inputs, results and callbacks. Old 403/404/401 responses cannot revalidate/navigate/close a new scope or refresh a new account's cookies.

Client cancellation does not guarantee cancellation of backend embedding or Agent work already accepted. There is no backend cancellation API or claim of cost rollback.

## 9. Error handling and retry

Only safe allowlisted codes from actual sources are translated: five retrieval validation/database/model codes; embedding timeout/unavailable/configuration mismatch plus actual provider configuration/response-validation errors; Agent disabled/model-not-configured/timeout/execution-failed/invalid-response. All 23 mapped codes have en/pl translations.

Unknown codes use safe status/generic messages; raw detail, stack traces, API keys, private provider messages, internal paths and private URLs are never rendered. Network status 0 gets an explicit localized network failure. 401 reuses existing identity-safe refresh, including its possible single transport retry; the UI/React Query adds no automatic POST retry loop. 409, 422 and 5xx have safe errors and explicit manual Retry. AbortError is normal cancellation and has no business-error UI.

403 stops local admission and revalidates existing Membership. 404 rechecks the current Base; confirmed missing Base uses exact base-prefix cleanup. The existing facade separately confirms Workspace loss. A current request error alone does not clear unrelated Bases or Workspaces. A still-valid scope can be retried manually. Scope and sequence leases also guard the revalidation callbacks.

Agent disabled or model-not-configured is shown as unavailable; Retry goes to the same endpoint and never substitutes another model. Form input is retained on ordinary errors. The ErrorState Retry action performs validation and fresh read preflight again.

## 10. Tests

Use real QueryClient, Knowledge Hooks, Auth Store and API facade, mocking only HTTP and UI environment boundaries. Deferred responses cover stale success/errors and cancellation; no real Provider call occurs.

Coverage includes parameter boundaries and defaults, zero/null similarity, invalid finite/integer values, 2000/2001 emoji and Python whitespace semantics, actual metadata/order/scope filtering, empty results, inert malicious text and rendering bounds, answered/no_evidence/sourceless replies, backend error-code mappings, owner/admin/member, pending/error/revoked Membership and invalid Base admission, fresh read preflight and shared-preflight latest-wins, duplicate submits, mode switch/drafts, Cancel, Workspace/Base/auth transitions, deleted/revoked scopes, old 403/404/401 callbacks, current 401 refresh success/failure, manual retry, unknown response/error states, StrictMode and en/pl key parity.

All original 647 tests and their assertions are preserved, including Knowledge Base CRUD, Document 104, Index 93, Workspace/Workflow/RBAC, authentication races and Knowledge API/Proxy multipart/binary/Search/Ask tests. No old test fixture or assertion was changed for this Atomic. Coverage include list and thresholds are unchanged.

Executed verification is recorded in section 13.

## 11. Known limitations

- Only the frontend Playground is implemented; it reuses v0.11 services. HTTP-boundary frontend tests do not prove actual retrieval quality, Agent grounding, vector DB state, worker execution or provider availability.
- No real paid Embedding/LLM Provider smoke call, browser-to-backend integration, Foundation Playwright E2E or live browser visual/mobile validation was performed. Linux Node 24 can be validated later in CI / Atomic 8.
- Docker Desktop remains user-closed. No containers were created/resumed, no Backend/PostgreSQL/Redis/Celery service or WSL/Linux environment was started/installed, and Atomic 2 temporary containers were not modified.
- Membership is checked at entry and before submission, with backend authorization decisive. There is no real-time revocation push subscription.
- The 10,000-character cap is display-only; full response text can exist transiently in memory. There is no server-side chunk/answer pagination or expandable full-text viewer.
- Search rows can be checked by base ID; Ask source DTO has no such field and relies on the protected response scope. The UI neither invents nor independently authenticates citations.
- Cancel cannot retract already accepted backend work. Mode changes discard results; this is a single-turn playground, not a conversation history.

## 12. Deferred features and Git boundaries

No new retrieval backend, Agent runtime, embedding provider, database/migration, dependencies, global navigation or version changes. No streaming, sessions/memory/history, model/prompt controls, source navigation, automatic indexing or fabricated statistics/cost/progress. Atomic 6 was not started.

All changes remain local for ChatGPT review. Branch/HEAD must remain the exact baseline; no branch create/switch, git add/commit/push/merge/reset/stash, PR, tag or release action is authorized or performed.


## 13. Executed final verification (Windows)

Runtime: Windows, Node v22.13.0, Bun 1.3.14, Next.js 15.5.23. Existing local backend Python stdlib confirmed that U+0085/U+001C strip to empty, FEFF does not, and 2000 emoji have Python length 2000; no Backend service was started.

| Command/check | Actual result |
| --- | --- |
| Initial Git/CI gate | PASS: clean main / exact baseline HEAD / diff check; Main CI #184 completed/success, all 16 jobs successful before modification. |
| `bun install --frozen-lockfile` | PASS, exit 0, 839 installs across 950 packages checked, no changes. Existing Husky prepare message: `.git can’t be found`. |
| `bun run lint` | PASS, exit 0, 0 errors / 13 existing warnings, no new Playground warnings. |
| `bun run type-check` | PASS, exit 0. |
| `bun run test:run` | PASS, 770 tests / 31 files, original 647 plus 123 new Playground tests; no skipped tests. |
| `bun run test:coverage` | PASS, 770 tests / 31 files, original coverage policy unchanged. |
| `bun run build` | PASS, exit 0; existing runtime-config deprecation and unrelated accessibility warnings remain. |
| `bun run test:run -- src/components/knowledge/knowledge-playground.test.tsx` | PASS, 123 tests / 1 file. |
| Knowledge component regression (`src/components/knowledge`) | PASS, 405 tests / 5 files, including unchanged Document 104 and Index 93. |
| `git diff --check` | PASS. New-file whitespace also checked. |
| Linux Node 24 / browser-to-backend integration / Foundation Playwright / real paid Provider smoke | NOT RUN for this local Atomic. |

Coverage remains limited to the original auth-cookies.ts, utils.ts, auth-store.ts and button.tsx files: aggregate statements/lines 69.23%, branches 100%, functions 60.86%. These are not coverage percentages for the new Playground. Existing thresholds remain statements 50, branches 90, functions 40, lines 50; no includes, assertions or thresholds were weakened.

Ignored local logs: `frontend/node_modules/.cache/atomic5-{target,target-regression,lint,type-check,test-run,test-coverage,build}.log`.

## 14. Final file/Git accounting

New (4): `knowledge-playground.tsx`, `knowledge-playground-utils.ts`, `knowledge-playground.test.tsx`, this document.

Modified (5): en/pl translations, KnowledgeBaseDetail Playground integration, KnowledgeBaseList content-prop type for optional read preflight, KnowledgeManagement scoped fresh-read preflight. Existing Knowledge Hooks, facade, proxy, authentication, Document/Index production logic and all old test files are unchanged. Backend, database/migrations, dependencies/lockfiles, CI, navigation and version files are unchanged.

Final branch `main`, HEAD `95297feebe9ca2319c125db3489dabea3cdd046c`, unchanged. Five tracked modifications and four untracked new files, all local and unstaged. No branch create/switch, git add/commit/push/merge/reset/stash, PR/tag/release or Atomic 6 work occurred. Awaiting ChatGPT review before any later Git publication instruction.
