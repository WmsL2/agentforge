# AgentForge v0.12.0 release preparation

Status: release preparation; not yet published.

Target release title: **AgentForge v0.12.0 - Knowledge Frontend**. Local metadata alignment and this document create no tag, GitHub Release or deployment. Maintainer review, current CI and promotion remain outstanding.

## Release scope and architecture

v0.11 supplies the Knowledge backend, private document storage/parser, pgvector indexing/retrieval, Knowledge Agent and durable Workflow Knowledge execution. v0.12 adds browser management and configuration over those existing services. Web Engineering Foundation (FastAPI/Next.js/auth infrastructure) remains distinct from the custom Agent Platform Core (runtime/tools/workflow/durability/knowledge).

Browser → existing apiClient → same-origin Next API proxy → existing FastAPI services. Workspace-scoped hooks and caches implement current frontend access/operation boundaries; backend RBAC remains authoritative. This release preparation adds no runtime, workflow engine, migration, provider architecture or third-party dependency.

## New capabilities and user operation guide

1. Open Knowledge from the dashboard, choose an accessible Workspace and inspect its Knowledge Bases. OWNER/ADMIN can create, rename and delete bases; MEMBER has read access and can use retrieval.
2. In a base, upload a supported nonempty document (PDF/DOCX/TXT/MD/MARKDOWN, up to 10 MiB). Inspect parse status, preview available parsed text, download the authenticated original or confirm deletion. Parsing failure can still leave a saved document; do not assume upload should be repeated.
3. Build an index and watch the actual pending/running/succeeded/failed state. Acceptance does not mean completion. Rebuild requires confirmation; a failed rebuild can leave the previous active index intact. No fabricated vector/job progress is shown.
4. Search with query, top_k 1–20 and optional minimum similarity, or Ask a standalone question. Sources are actual backend retrieval items. no_evidence is not an execution error or proof of missing documents; similarity is not model confidence.
5. In a Workflow canvas, add a Knowledge node, choose a verified current-workspace base, choose literal query or a top-level workflow input key, and set top_k 1–5. Apply the draft, connect a valid DAG, then Save. Save still validates server-side before PATCH. An Agent may optionally bind one base while preserving runner/instruction/model; clearing the binding restores ordinary Agent behavior.
6. Run the saved revision. Knowledge steps show retrieval evidence; bound Agent steps show answers and actual Sources. Historical results use the selected Run's immutable definition_snapshot, not the current editor. Raw JSON, Steps, Trace and existing approval controls remain available within their authorization boundaries.

## Upgrade and deployment requirements

- From v0.11, this preparation requires no new database schema. Alembic head remains `0046_add_workflow_run_actor_identity`. Earlier upgrades must apply the existing v0.11 migration chain; see [v0.11 notes](release-v0.11.md).
- Preserve PostgreSQL 16 / pgvector 0.8.7, Redis 7, API, Celery Worker and Beat configuration. The frontend alone does not index or run Agents. Back up the database and private media together before deployment; verify restore consistency.
- Retain existing `EMBEDDING_*` credentials/model/dimensions (1536) and `LLM_*` configuration. The dedicated Ask API's `KNOWLEDGE_AGENT_ENABLED` flag is distinct from Workflow Agent knowledge composition. Configure only intended, authorized providers; use a secret store.
- Install backend/frontend with frozen lockfiles. AgentForge metadata targets 0.12.0 across distribution/runtime/FastAPI/CLI/frontend. No third-party version upgrades or frontend lockfile root version field were added.
- Linux Node 24 validation remains outstanding; local Windows Node 22 validation is recorded separately. Existing CI service images are unchanged.

## Security and trust boundaries

Knowledge routes preserve Workspace/base/document scope and authenticated private-file access. User/config/model fields cannot supply trusted workspace or actor identities. Backend execution rechecks actual authorization; persisted Run/Trace visibility follows RUN_READ. Retrieval evidence is not factual certification of generated prose or external-tool DLP.

Run reads retain session generation/epoch keys and signal/identity guards. Confirmed 403/404 denial persists across later temporary failures and Run switches; only that resource's new successful identity-matched HTTP read clears it. AbortError and 403/404 do not automatically retry. Raw diagnostics do not bypass run/workflow ownership or known denial. External answer/content text is bounded and rendered as text, without generated document links, HTML execution or inferred citations.

## Verification matrix

Evidence layers must remain separate. Detailed executed commands and counts are in [Atomic 8 integration record](v0.12/atomic8-integration-release.md).

| Layer | What it verifies | Current local evidence |
| --- | --- | --- |
| 1 — frontend unit/integration and offline backend tests | Components, hooks, HTTP contracts, lifecycle and metadata | Executed; see actual results in Atomic 8 record. |
| 2 — browser with HTTP mock | Real pages/frontend chain plus deterministic stateful responses | 16 new scenarios authored; Chromium discovery checked. Browser execution NOT RUN because live login setup/services are unavailable locally. |
| 3 — existing backend integration E2E | PostgreSQL/pgvector, Redis, real Celery and deterministic provider | Existing v0.11 lifecycle CI retained. NOT RUN locally for this change; requires current post-review CI. |
| 4 — live full-stack staging smoke | Deployed auth/API/DB/worker and authorized provider behavior | NOT RUN. Checklist below remains unchecked. |

Main CI #193 / 26 historical Playwright passes are supplied baseline evidence only. Discovery is not execution; independent Layers 2 and 3 never establish Layer 4. No current PR/CI result is claimed before an authorized publication step.

## Staging smoke checklist — NOT RUN

Use a dedicated temporary Workspace, named synthetic fixtures and isolated queues/provider budget. Record run/job IDs in internal evidence without exposing secrets. Obtain provider cost authorization, set spend/rate limits and back up the test database/private media before any changes.

- [ ] Deploy reviewed artifacts; verify 0.12.0 on distribution, FastAPI, CLI and frontend; verify migration head and pgvector extension version.
- [ ] Login with real authentication, create a temporary Workspace/base and add a test member.
- [ ] Upload a synthetic text document; inspect parse/preview/download and confirm private unauthenticated/cross-workspace reads fail.
- [ ] Submit indexing; observe the same job pending → running → succeeded with an active generation.
- [ ] Search known text; inspect actual chunk/document/page/score fields.
- [ ] Ask an answerable and unsupported question; inspect real Sources and no_evidence behavior and review provider cost/answer quality separately.
- [ ] Create/apply/connect/validate/save/reopen a Knowledge Workflow and an Agent-bound Workflow.
- [ ] Run both against real workers; correlate selected Run ID, immutable revision/snapshot, Steps and Trace. Confirm evidence comes from Step output.
- [ ] Test approval/resume with a different authorized approver; original submitting actor must be retained.
- [ ] Compare historical runs before/after binding changes in both directions.
- [ ] Revoke membership; verify real API denial, hidden cached bodies, logout/relogin isolation and fresh authorized recovery after access restoration.
- [ ] Exercise failed reindex (old active generation retained), then successful reindex.
- [ ] Delete synthetic documents and bases through authenticated APIs; inspect worker completion/private-file cleanup, remove test membership/Workspace and review backups/restore procedure.

## Known limitations and release checklist

No multi-KB retrieval, hybrid search, reranking, GraphRAG, conversation memory, new provider/runtime or large UI redesign. Browser HTTP fixtures do not execute embeddings, parsing, SQL, workers or LLMs. New browser scenarios are not locally runtime-validated; selectors, React Flow interactions and timing still require the existing authenticated Chromium CI gate. Existing type/deprecation warnings and gated tests are disclosed in the integration record.

- [ ] ChatGPT implementation/source review accepted; Atomic 8 is not declared COMPLETE by this local preparation.
- [ ] Current CI after authorized commit/PR passes all existing jobs plus the two added browser specs; no tests/security gates reduced.
- [ ] Linux Node 24, full intended Chromium suite and real backend lifecycle proof pass in their proper environments.
- [ ] Staging smoke, provider budget/quality, deployment and backup/restore review accepted.
- [ ] Authorized maintainer decides publication of any branch/tag/Release/deployment. This task performs none; v0.13 is out of scope.
