# v0.12 Atomic 6 — Workflow Knowledge Editor

## 1. Baseline and scope

Implementation started from clean `main`, HEAD `a5752f8410821de044296cb7a811b260df14a5e7`, after Atomic 5 / PR #35. Read-only initial Git checks passed. Main push CI [#186](https://github.com/WmsL2/agentforge/actions/runs/45142032820) was independently queried and returned completed/success for this SHA; the supplied baseline reports 16/16 jobs, 770 frontend tests and 26 Playwright tests. Individual CI jobs and Playwright were not rerun locally in this Atomic.

v0.11 already implements backend Knowledge nodes and Agent Knowledge Tool composition. This Atomic adds their frontend editor only. Version remains 0.11.0. No backend, authentication infrastructure, global RBAC, schema, dependency, lockfile, CI or version changes.

## 2. Source review

Reviewed workflow types, canvas rules/adapter/canvas/editor/Inspector/detail, Knowledge hooks/facade/lifecycle, Workflow API, existing tests and v0.11 Atomic 6/7 documentation. Backend domain model, validator, Knowledge executor and Agent executor/composition were read without modification.

Actual backend contracts determine the form. Knowledge returns retrieval evidence, not an LLM answer. Agent binding enables existing backend tool composition. Trusted workspace/actor identities remain backend/runtime inputs and are never added to node config. Workflow input lookup uses a literal top-level key, not a dotted path or node-output expression.

## 3. UI and component architecture

Existing WorkflowCanvas gains Add Knowledge using the same node ID and placement rules, without generating edges or executing retrieval. Existing NodeConfigurationEditor owns both forms through its original draft/apply callbacks. A shared KnowledgeBasePicker serves Knowledge and Agent. Small workflow-specific helpers validate UUID strings, Python-compatible whitespace and top_k.

The generic existing canvas adapter already serializes these node configs; it required no production change. No second editor, new navigation or global state layer was introduced. en/pl keys live under workflows.canvas and have tested parity.

## 4. Knowledge node configuration

New nodes start with an intentionally incomplete draft:

```json
{"knowledge_base_id":"","query_source":"literal","query":"","top_k":5}
```

Apply requires an API-confirmed current-workspace Knowledge Base, a syntactically valid UUID, and integer top_k 1–5. Literal mode requires query length 1–2000 Unicode code points after Python-compatible whitespace removal. Workflow-input mode requires a nonblank input_key. The input key itself is preserved, because the executor uses the exact key.

Switching modes removes the opposite draft value; Apply removes the opposite config field. Config allowlists reject unknown fields, including identity, min_score, output mapping and template fields. Apply copies config immutably; rendering does not rewrite historical config. UUID spelling normalization is used for verification/read lookup, without silently changing stored historical config or adding UUID version restrictions.

## 5. Agent Knowledge binding

Agent keeps runner=langgraph, instruction and optional model. Optional knowledge_base_id can be selected or removed. Ordinary Agents do not acquire a binding merely by rendering. Clearing removes the field rather than storing an empty UUID. Agent does not receive Knowledge node query_source/query/input_key/top_k. Existing valid fields and node metadata remain intact; unsupported fields remain blocked.

## 6. Knowledge Base selector

The picker reuses useKnowledgeBases, useKnowledgeBase and the existing protected facade/lifecycle. Lists use skip/limit pagination (10 per page) and API total. Options require a fresh completed response, valid ID and matching workspace_id; injected DOM options cannot become accepted IDs.

A selected historical ID is checked with its scoped detail endpoint, independent of the visible list page. Absence from page one does not clear or substitute the binding. While checking, the UI reports verification pending; failed/missing bindings remain visible as unavailable and cannot be applied as verified resources. Empty, loading, list error, retry, selection retry, pagination and read-only states are explicit. No fake base, automatic selection, creation, polling or provider call is made.

## 7. WorkflowGraph serialization

Knowledge and Agent binding pass through the existing Canvas → WorkflowGraph → backend validation → PATCH chain. schema_version is unchanged. Round-trip tests preserve graph/node/edge metadata and coordinates. Unique IDs, duplicate-edge/self-loop/START-input/END-output/cycle rules and deletion of connected edges remain in force.

## 8. Draft, dirty, validation and save

Typing changes only Inspector draft. Applied graph config and backend remain unchanged until Apply and Save respectively. Pending drafts continue to block Validate/Save; drafts survive node switching. Discard and deletion confirmation reuse existing behavior. Selection alone stays clean; graph edits become dirty. The editor retains its unsaved-leave guard and failed-PATCH data.

Save still performs authoritative server validation before PATCH. Invalid server responses block PATCH. Remote revision conflicts preserve unsaved work. Session keys include user/workspace/workflow/auth generation and epoch, but not revision, so a revision update does not discard conflict state.

## 9. Workspace isolation and RBAC

Existing workspace membership-based workflow editing is retained; global App Admin is not substituted for workspace membership. Production picker authorization follows the existing membership query. At Apply, the selected binding proof rechecks the live membership cache and Knowledge detail cache, including query success/idle status. This closes the interval between cache mutation and React notification: clicking an old Apply button cannot apply a revoked/refetching binding.

Readonly Inspector cannot mutate config. The picker scopes every list/detail read by user and workflow workspace, filters returned ownership and retains backend authorization as decisive. There is no realtime membership revocation subscription; protection reacts to existing query/lifecycle updates and backend requests.

## 10. Authentication boundary and errors

Auth Store and identity coordinator are reused without modification. User, workspace, workflow, logout and same-user login changes isolate editor/picker sessions. Verification callbacks recheck mount state, generation/epoch, selection, resource lifecycle and live caches at action time. Old HTTP completions cannot supply the new Inspector. Selected-base deletion clears its verification; workspace/user lifecycle clearing invalidates the session.

List errors, unavailable bindings, invalid UUID/query/input key/top_k, backend validation failure, save failure and revision conflict have separate safe states. Workflow HTTP failures use translated status-based messages rather than raw private error details. New Knowledge validation issues use a safe translated message; existing unrelated validation rendering remains unchanged. No untrusted HTML is generated.

## 11. Tests and executed verification

Executed on Windows on 2026-11-23: Node v22.13.0, Bun 1.3.14. Tests retain real React Query, Knowledge hooks and Auth Store with HTTP-boundary mocks. Canvas tests mock the XYFlow rendering boundary; editor integration tests use a canvas seam with the real Inspector. They do not constitute browser or real-backend E2E.

New tests: workflow-knowledge-editor.test.tsx (58) and knowledge-canvas.test.tsx (22). Coverage includes node creation/movement/connection/deletion/round-trip, mode exclusivity and Unicode boundaries, UUID/top_k errors, Agent binding/clearing, historical/paginated selection, foreign/injected options, loading/error/retry, delayed scope/auth transitions, resource deletion, membership loss including immediate stale-button clicks, readonly, StrictMode, drafts/dirty/discard/conflict, validate-before-PATCH and safe errors/i18n.

| Command/check | Actual result |
| --- | --- |
| `bun install --frozen-lockfile` | PASS, exit 0; 839 installs across 950 packages checked, no changes. Existing Husky `.git can't be found` message did not fail installation. |
| `bun run lint` | PASS, exit 0; 0 errors, 13 existing warnings. |
| `bun run type-check` | PASS, exit 0. |
| `bun run test:run` | PASS, 850 tests / 33 files: all original 770 plus 80 new, no skips. |
| `bun run test:coverage` | PASS, 850 tests / 33 files; coverage configuration and thresholds unchanged. |
| `bun run build` | PASS, exit 0; existing runtime-config deprecation and unrelated lint warnings remain. |
| New two-file targeted run | PASS, 80 tests. |
| Final targeted new + existing regression run | PASS, 219 tests / 8 files. Includes workflow-canvas, workflow-canvas-editor, node-configuration-editor, canvas-rules, canvas-adapter, knowledge-management and both new files. |
| Backend/frontend validation-code comparison | PASS, 41 codes each, no missing/extra codes. Backend read-only. |
| `git diff --check` and new-file whitespace | PASS. |
| Linux Node 24 / Playwright / real Backend or Provider E2E | NOT RUN. |

Coverage remains scoped to the existing auth-cookies.ts, utils.ts, auth-store.ts and button.tsx: statements/lines 69.23%, branches 100%, functions 60.86%. These are not percentages for the new editor. Thresholds remain statements 50, branches 90, functions 40, lines 50. No original tests were deleted, skipped, weakened or modified.

Local ignored logs are frontend/node_modules/.cache/atomic6-{lint,type-check,test-run,test-coverage,build,regression}.log.

## 12. Known limitations

No live browser visual/mobile verification, Linux Node 24 run, local Playwright execution, real-backend workflow run or paid LLM/Embedding request was performed. The previously supplied 26 E2E tests are baseline information, not a new local PASS. Current local changes require subsequent CI/review verification. Frontend tests do not prove actual retrieval quality, grounding, vector database state or provider availability.

Membership/base revocation becomes known through existing queries and lifecycle notifications, not a new push mechanism. Server validation and execution authorization remain authoritative. A verified base can change after form Apply; save validation/runtime remain necessary and are not bypassed.

## 13. Deferred features

No Atomic 7. No new backend retrieval/Agent runtime, output mapping, query templates, node-output query source, score filtering, indexing controls, runtime execution UI, streaming, dependency, schema or version change.

## 14. File and Git boundaries

Modified (7): en.json, pl.json, workflow types, canvas-rules, workflow-canvas, workflow-canvas-editor and node-configuration-editor. New (5): knowledge-config helper, shared picker, two test files and this document. Existing adapters, Knowledge hooks/facade, Auth Store/coordinator, backend and old test files are unchanged.

All changes remain local and unstaged on main at a5752f8410821de044296cb7a811b260df14a5e7. No branch creation/switch, git add/commit/push/merge/reset/stash/rebase, PR, tag or release action was performed. No Docker/containers, Atomic 2 leftovers, WSL, Backend, PostgreSQL, Redis or Celery were started or operated. Awaiting ChatGPT review.
