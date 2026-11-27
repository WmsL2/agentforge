# AgentForge v0.13 — Confirmed Eight-Atomic Roadmap

Date: 2026-11-24. Planning baseline: `main`, exact HEAD and peeled `v0.12.0` tag `6e4cca6bc188d829bc09431080b08ad86e37f3fb` (Knowledge Frontend).
Status: confirmed scope and acceptance plan for maintainer review. This document implements no fixes, starts no later Atomic, authorizes no infrastructure or publication, and declares no Atomic COMPLETE.

Source findings and classifications: `docs/v0.13/atomic1-production-architecture-audit.md`, sections 1–17. Supplied [Main CI #197](https://github.com/WmsL2/agentforge/actions/runs/45356348423), SUCCESS 16/16 jobs, is historical baseline evidence only. No new CI or production success is claimed.

## Shared scope, evidence and authorization rules

Preserve the Repository + Service foundation and existing Agent Platform Core. Reuse multi-stage/non-root/frozen Docker builds, PostgreSQL 16/pgvector 0.8.7, Redis 7, Celery Worker/Beat, Settings validators, SQLAlchemy sessions/task-local engines/disposal, liveness/readiness, RequestIDMiddleware, PII filter, Secure/HttpOnly cookies, Workspace RBAC, checkpoint/claim/lease/fencing and both recovery scanners. Preserve private path checks, commit compensation and existing document reconciliation, plus browser/backend integration tests.

KnowledgeIndexExecutor uses PostgreSQL parsed_content. Shared media stores private originals; the roadmap must not assume indexing rereads original files. Existing bounded upload/parser/chunk/provider settings and Compose resource declarations must be extended where needed, not described as absent.

Non-goals for every Atomic: Kubernetes, microservices, multi-agent orchestration, GraphRAG, hybrid retrieval, reranking, Agent Memory, billing redesign or a redesigned platform core. No generic workflow retry/outbox/exactly-once redesign is implied. Provider cost controls are bounded operational safeguards.

The present authorization is documentation-only: create the two Atomic 1 documents, locally and unstaged. All future runtime checks, tests, builds, drills, infrastructure and Git publication below are **planned acceptance requirements**, not commands executed or permission granted now. Future Atomic work requires its own scope/baseline authorization. Existing real services/private data must not be touched on the assumption that staging is harmless.

Keep evidence layers distinct: unit/integration; browser HTTP mock integration; real backend PostgreSQL/Redis/Celery E2E; backend image build; production Compose runtime; live full-stack staging; commercial Provider smoke; paired DB/media restore drill. All are NOT RUN in Atomic 1 except documentation/static validation. Historical CI never substitutes for an unexecuted runtime layer. Never print actual credentials, Settings dumps, raw sensitive errors or authentication storage.

## Atomic 1 — Production Architecture Audit

- **Objective:** verify the exact v0.12.0 tracked-source architecture, persist classified findings and this eight-Atomic plan.
- **Existing implementation to reuse:** tracked architecture/deployment/configuration/release documents, production/dev Compose, source/tests/CI and supplied historical baseline evidence.
- **In-scope changes:** only `docs/v0.13/atomic1-production-architecture-audit.md` and `docs/v0.13/roadmap.md`; architecture/data-flow diagram, capabilities, findings, responsible owners, evidence boundaries, corrections and acceptance limitations.
- **Out-of-scope changes:** all fixes, existing files, source/tests/dependencies/version metadata, runtime inspection/execution and Git publication.
- **Dependencies:** clean main, exact required HEAD/tag, empty staged diff and passing initial whitespace check. Any baseline failure stops work without repair/reset/stash/switch.
- **Expected verification:** required headings and finding IDs; all eight definitions and required fields; actual tracked reference paths/line bounds; consistency; both untracked files' whitespace; final diff/status/branch/HEAD and staged checks. No application suite solely for docs.
- **Acceptance criteria:** two reviewable evidence-grounded documents only, every supplied finding verified or qualified, existing capabilities preserved, no runtime results fabricated, changes local/unstaged and report delivered for review. Do not declare COMPLETE.
- **Operational authorization requirements:** no Docker/WSL/container changes, migrations, DB access, Provider calls, private-media mutation, reconciliation, infrastructure or Git mutations. No Atomic 2 work.

## Atomic 2 — Configuration & Secrets

- **Objective:** establish one coherent, capability-aware production configuration and safe-error contract using existing Settings.
- **Existing implementation to reuse:** `backend/app/core/config.py` Settings/validators/computed URLs; public env examples; API/worker composition inputs; separate Platform Runtime, legacy chat and Embedding settings.
- **In-scope changes:** dev/prod input isolation and explicit role environment consistency; required/placeholder validation for DB/Redis/JWT/API/Flower and enabled Provider features; safe DB/Redis/Celery URL construction; input/computed-field documentation; bounded safe validation/readiness errors. Primary findings P0-01 and P1-01–P1-04, P1-10, P2-09; deployment realization belongs to A3 and health presentation to A4.
- **Out-of-scope changes:** new secret/config framework, provider architecture, secret rotation against real systems, deployment/migrations, feature expansion, metrics platform, billing or workflow redesign.
- **Dependencies:** accepted A1 findings and separately authorized implementation scope. Coordinate A3 role/env/Compose contract and A4 diagnostic consumers.
- **Expected verification:** synthetic positive/negative Settings cases independent of local dotenv; production placeholder/empty/missing checks; reserved-character URL round-trips; consistent API/Worker/Beat values; feature-gated LLM/Embedding requirements; validation errors free of values/URLs/credentials.
- **Acceptance criteria:** development remains usable, production fails early on invalid required inputs, every runtime role uses the same intended environment/credential contract, URLs preserve credentials, public validation is bounded and safe; no claim that configured providers are connected.
- **Operational authorization requirements:** actual secret reads/rotation, DB connections, containers and Provider calls are not implied. Use synthetic config tests; any real environment work requires explicit target/action authorization.

## Atomic 3 — Deployment Infrastructure

- **Objective:** make the existing single-host production deployment reproducible and correctly ordered.
- **Existing implementation to reuse:** multi-stage/non-root/frozen builds, named volumes, PostgreSQL/pgvector/Redis, Worker/Beat/Flower roles, existing Alembic migration chain and service dependencies.
- **In-scope changes:** one versioned backend release image/digest shared by all roles; coherent authenticated broker wiring; migration-success gate before business startup; explicit production role configuration; project/resource isolation; persistent volumes; controlled provider network egress; safe command/deploy contract and reproducible artifact inputs. Primary P0-02–P0-04, P1-05, P2-01; realizes P0-01/P1-01/P1-04 with A2. Supply network/proxy integration seam to A6 and image identity prerequisite to A4.
- **Out-of-scope changes:** Kubernetes, microservices, cloud provisioning by default, destructive volume reset, platform-core redesign, production rollout and new migration/schema features unrelated to deployment.
- **Dependencies:** A2 configuration contract; accepted A1 findings. A4 specifies role probes; A6 specifies final ingress/egress security policy; A7 proves final integrated deployment.
- **Expected verification:** safe sanitized config validation, isolated backend/frontend builds, backend role digest equality, migration success/failure ordering, service dependency proof, independent project identities/volumes, persistence across authorized restart, deterministic provider egress from actual callers.
- **Acceptance criteria:** fresh isolated deployment uses intended release artifacts, business roles cannot start before successful migration, failed migration blocks them, environment resources cannot collide, persistence is explicit and provider egress does not expose DB/Redis. Verification records effective behavior, not only YAML intent.
- **Operational authorization requirements:** builds/start/stop/restarts/migrations require explicit isolated project/network/port/volume/database targets. No Docker/WSL action, production mutation or data deletion under A1 authorization. Commercial calls remain separately authorized.

## Atomic 4 — Operational Observability

- **Objective:** make health, logs and minimal metrics truthful and useful for operating the existing system.
- **Existing implementation to reuse:** current live/ready/basic/alias endpoints, frontend health proxy, RequestIDMiddleware, PiiRedactionFilter, existing task IDs/run IDs and recovery result counters, RunStep/Trace where relevant.
- **In-scope changes:** status-aware bounded API/frontend checks; role-correct Worker/Flower checks and explicit Beat semantics; distinguish configured Worker/Provider from connected; safe bounded health diagnostics; handler/formatter/worker redaction coverage; bounded request correlation and task propagation; minimal protected low-cardinality runtime/recovery metrics; health contract docs/release identity clarity. Primary P1-06–P1-09, P1-11–P1-12, P2-02; integrate A2 P1-10 and A6 resource signals.
- **Out-of-scope changes:** replacing health/logging stack, automatic paid LLM probes, dashboards/large monitoring platform, observability redesign, sensitive payload logging and arbitrary high-cardinality labels.
- **Dependencies:** A2 safe error/config contract and A3 service/image identity. A6 determines diagnostic/metrics exposure. A7 exercises final effective checks.
- **Expected verification:** healthy/non-2xx/timeout/dependency-failure cases; real Worker responsiveness in authorized isolation; no Provider connectivity inference from keys; root/descendant/handler/Celery/exception/structured synthetic redaction cases; safe correlation and metric access/cardinality checks.
- **Acceptance criteria:** each health signal states exactly what was checked, failures are meaningful for its role, public errors are bounded, sensitive exception/extra fields have effective coverage, metrics are minimal and restricted, existing execution traces and endpoints remain compatible where required.
- **Operational authorization requirements:** offline synthetic checks first; worker/container failure injection only against explicitly isolated resources. No commercial calls in routine probes or incidental diagnostics, no actual secret inspection.

## Atomic 5 — Reliability & Recovery

- **Objective:** validate interruption/shutdown behavior and paired DB/private-media recovery using existing durability mechanisms.
- **Existing implementation to reuse:** workflow checkpoints/snapshots, claims/leases/fencing, WorkflowRecoveryScanner, KnowledgeIndexRecoveryScanner, index heartbeat/generation switching, late acknowledgements, task-local engines/disposal, storage path validation/compensation and reconcile_orphans.
- **In-scope changes:** targeted reliability hardening when proven necessary; controlled interruption/redelivery/stale-claim recovery; graceful shutdown; paired backup/restore runbook and isolated drill; private-media consistency and safe existing reconciliation invocation; writer quiescence/locking and reviewable candidates. Primary P1-13–P1-14, P2-08. Preserve different workflow/index heartbeat contracts rather than assuming equivalence.
- **Out-of-scope changes:** competing orphan cleaner, destructive production cleanup, new orchestration/recovery framework, exactly-once external effects, general retries/outbox or billing.
- **Dependencies:** A2 consistent settings, A3 isolated deployment/migration ordering and A4 diagnostics. A6 controls backup/private storage access; A7 reruns integrated failure scenarios.
- **Expected verification:** deterministic interruption before/after commit, broker publication failure, duplicate delivery, lease takeover/stale fencing, checkpoint resume, index reindex failure retaining old generation, cleanup/disposal/shutdown; isolated paired restore with schema/pgvector/file-hash/authenticated-download checks and pending recovery; concurrent-upload reconciliation safety.
- **Acceptance criteria:** committed state recovers without stale writes; external-effect limitations remain explicit; restored DB/media agree; runbook defines RPO/RTO/retention/access/resume criteria with measured drill evidence; reconciliation cannot delete valid in-flight files under its documented maintenance constraints.
- **Operational authorization requirements:** explicit disposable targets and permission for process interruption, DB/media backup/restore and any synthetic deletion. Real production backup/restore/reconciliation is not authorized by this roadmap; no private media deletion without separate explicit scope.

## Atomic 6 — Production Security Hardening

- **Objective:** enforce production ingress/egress, data protection and bounded operational resource/cost policies.
- **Existing implementation to reuse:** JWT/API dependencies, Workspace RBAC, Secure/HttpOnly/SameSite cookies, CORS/security headers, internal DB/Redis network attachment, private storage validation, dockerignore files, existing upload/parser/chunk/provider limits and Compose resource declarations.
- **In-scope changes:** TLS/reverse-proxy/trusted-forwarding policy; HTTPS/WSS and Cookie/CORS alignment; restrict API/Flower/health/metrics exposure; protect private storage/backups and build context; resource/queue/storage/request/concurrency/time limits; bounded Provider cost controls; explicit vulnerability scan triage/gate policy. Primary P1-15–P1-17, P2-03, P2-05; final security policy for P0-03 and A4 endpoints.
- **Out-of-scope changes:** replacing auth/RBAC/platform core, billing/subscription product, new DLP claims, external penetration testing or commercial Provider calls by default, unrequested cloud infrastructure.
- **Dependencies:** A2 validation/secret contract, A3 deployment/network resources, A4 diagnostics/metrics, A5 private-media/backup operational procedures.
- **Expected verification:** controlled HTTPS/WSS login/refresh/logout and revocation; Cookie/CORS/forwarded-header/host exposure checks; restricted management/diagnostic access; synthetic build-context markers absent from layers; enforced bounds under deterministic overload; actual vulnerability findings/dispositions rather than successful-job inference.
- **Acceptance criteria:** documented supported TLS/proxy setup exists, published ports match policy, auth/private files remain protected, builds exclude private artifacts, resource/provider costs are bounded without billing expansion, security checks are retained and scan results are interpreted honestly.
- **Operational authorization requirements:** certificates/DNS/firewall/external proxy/host changes require named targets and explicit permission; no real secret reads, unapproved scan traffic or provider spending. Synthetic safe artifacts for build-context tests only.

## Atomic 7 — Full-stack Staging Validation

- **Objective:** establish real full-stack deployment evidence distinct from browser mocks and backend-only integration.
- **Existing implementation to reuse:** real auth/frontend API proxies, Workspace/RBAC, document APIs, pgvector indexing/retrieval, workflow/approval/Trace, both recovery mechanisms, existing deterministic Provider test services and backend/browser tests.
- **In-scope changes:** explicitly authorized isolated deployment with production artifacts and deterministic Provider services; exercise actual frontend/backend/auth/DB/Redis/worker document upload/preview/download/index/search/Ask/Knowledge and Agent workflow paths, saved revision/history, approval/resume, membership revocation, failure/recovery and operational checks. Primary P2-04, P2-06; verify P0 remedies and A2–A6 acceptance evidence. Commercial Provider smoke P2-07 is optional and separately authorized.
- **Out-of-scope changes:** treating HTTP fixtures as real domain E2E, using production accounts/data/queues, unapproved commercial calls, general feature development, production rollout and weakening existing tests/auth setup.
- **Dependencies:** A2–A6 implementation/evidence accepted; explicit resource manifest and deployment authorization; deterministic providers configured with explicit endpoints. Restore evidence from A5 is required and referenced independently.
- **Expected verification:** identify artifact digests, config identity without secrets, migration/pgvector revision, service health/egress and volume identities; real browser actions traced through API/DB/worker with run/job IDs; integrity, denial/revocation and recovery evidence; record each scenario PASS/FAIL/NOT RUN and cleanup disposition.
- **Acceptance criteria:** intended production deployment passes real connected workflows, no fixture intercepts the operations claimed as real, isolated resources are evidenced, all critical scenarios are resolved and independent verification layers remain distinct. Commercial availability/quality is never inferred from deterministic success; lack of authorization stays NOT RUN and is disclosed.
- **Operational authorization requirements:** user approval must explicitly identify isolated project, network, ports, volumes, database, test accounts/workspace, deterministic Provider endpoints, lifecycle/cleanup actions. Commercial smoke additionally needs endpoint/model, synthetic data/privacy boundary, spend/rate/time budget and stop conditions. No production mutation implied.

## Atomic 8 — Integration & Release

- **Objective:** integrate the accepted hardening, regression and operational evidence into a maintainer-controlled v0.13 release.
- **Existing implementation to reuse:** existing CI/security/test gates, release checklist/version metadata mechanisms, backend/browser E2E, deployment/recovery documentation and A1–A7 evidence.
- **In-scope changes:** complete regression appropriate to all changes; coherent deployment/recovery/config/security docs and removal of identified stale examples; version metadata alignment; evidence inventory and remaining limitations; Final Source Review; authorized PR CI, Main CI, tag and Release stages. Consolidate all finding dispositions, particularly P2 documentation/verification boundaries.
- **Out-of-scope changes:** unrelated features/dependency upgrades/platform redesign, declaring success from historical CI, suppressing failed/skipped checks, unauthorized deployment or automatic publication based on this plan.
- **Dependencies:** A1–A7 review accepted; required staging and restore evidence present; unresolved P0 blocks release readiness. Any remaining gap needs explicit maintainer disposition, never silent conversion to PASS.
- **Expected verification:** backend/frontend regressions and static checks, browser mock layer, real backend E2E, image/deployment/staging/restore evidence separately recorded; metadata agreement; Final Source Review; new PR CI and Main CI actual results inspected after authorized Git operations; final tag resolves to reviewed release commit.
- **Acceptance criteria:** no unresolved deployment blocker, all findings closed or explicitly accepted with limitations, documented commands match supported configuration, runtime evidence is reviewable, version/commit/CI/tag/Release identity aligns and maintainer promotion decision is recorded. Commercial smoke remains NOT RUN unless separately authorized and performed; release limitations must say so.
- **Operational authorization requirements:** local implementation approval does not imply add/commit/push/branch/PR/tag/Release or deployment authority. Maintainer controls separate Git/publication instructions and production rollout. No remote mutation under current Atomic 1 scope.

## Dependency and evidence handoff

Sequence: A1 → A2 → A3 → A4 → A5 → A6 → A7 → A8. Neighboring Atomics coordinate interfaces; later evidence may expose a targeted correction to an earlier implementation under an explicitly authorized scope. A3 network wiring is finalized against A6 policy before A7. A4 probe semantics depend on A3 image identity. A5 and A6 jointly protect restore artifacts/private storage. None of these dependencies permits starting future work in Atomic 1.

Every finding's primary remediation owner and expected evidence appear in the audit table. A7 demonstrates the integrated result; A8 consolidates review/release evidence. Operational commands and checklists are plans until actually authorized and executed. Current status: two local documentation additions only; all runtime checks NOT RUN; no new CI, deployment, Git mutation or later Atomic implementation.

## Maintainer-approved acceptance amendment — 2026-11-26

### Current positioning and precedence

**AgentForge v0.13 — Engineering Hardening** is the current maintainer-approved
positioning. The project serves job-application portfolios, Agent engineering
learning, technical demonstrations and interview preparation. Actual commercial
production deployment is not a project or release prerequisite.

The original 2026-11-24 roadmap above, its audit findings, owner assignments and
original acceptance requirements remain unchanged as historical context. This
dated amendment supersedes conflicting acceptance requirements in those historical
Atomic definitions, dependency notes and handoff gates. In particular, production
staging, real production deployment and a full production restore drill no longer
block merge/release by default. Their missing evidence remains explicit; it is
not relabeled PASS. Existing architecture, automated regressions, security checks,
durability semantics and authorization boundaries remain mandatory.

Atomic 1 and Atomic 2 are COMPLETE by the supplied maintainer status. Atomic 3 has
completed local implementation/review fixes and preserved historical offline
evidence, but remains pending Final Source Review and integration. No later Atomic
implementation starts in this documentation task.

### Revised Atomic 1 — Architecture Audit

- **Status:** COMPLETE; preserve the existing audit evidence, findings and classifications.
- **Objective and scope:** retain the evidence-grounded architecture baseline and finding ownership without rewriting the historical audit or redesigning the platform core.
- **Acceptance:** preserve the accepted audit and its limitations; this amendment does not rerun the audit or fabricate new findings/runtime evidence.

### Revised Atomic 2 — Configuration & Secrets

- **Status:** COMPLETE; preserve the existing implementation, review/security evidence and configuration boundaries.
- **Objective and scope:** retain capability-aware Settings validation, synthetic/offline tests, safe errors and URL construction, and role-consistent secret/configuration contracts.
- **Acceptance:** existing regression and security checks remain intact. Configured Provider settings still do not prove connectivity. No credential reads, rotations or implementation changes are authorized here.

### Revised Atomic 3 — Deployment Infrastructure

- **Status:** local implementation and review fixes retained; not COMPLETE.
- **Objective and scope:** preserve shared versioned backend artifacts, migration-success dependencies, project/resource isolation, repository/tag partition (RF-01) and Settings preflight before business stop (RF-02).
- **Mandatory acceptance:** exact source/scope review, existing offline regression evidence and security checks, Final Source Review, PR CI, maintainer-approved merge, Main CI and local synchronization. Historical focused 210/broader 389 passed results are retained, not rerun by this task.
- **Evidence disposition:** RV-Stage 1 and effective Compose validation PASS; 1,072 source-export files verified; RV-Stage 2 BLOCKED AT BUILD; Build Recovery 1 BLOCKED; actual deployment NOT RUN. Observed HTTPS/TLS/registry failures establish no conclusive root cause or source defect. Further local registry troubleshooting stops by maintainer decision.
- **Deferred acceptance:** actual production Compose deployment is optional/deferred, not a mandatory merge gate. Full production build remains BLOCKED; actual backend image-ID equality, migration success/failure gate, update behavior, dual-project isolation, production-Compose PostgreSQL/Redis authentication, deterministic Provider connectivity, volume persistence and production frontend runtime remain NOT RUN.
- **Evidence boundary:** retain section 19 of `docs/v0.13/atomic3-deployment-infrastructure.md`, including the missing Stage 2 historical dotenv checksum. This amendment grants no further runtime/Git execution authority.

### Revised Atomic 4 — Operational Observability

- **Objective:** truthful, role-appropriate health contracts and safe useful diagnostics for the existing system.
- **Reuse and scope:** current health endpoints, request correlation, structured diagnostics, sensitive-information redaction and minimal useful protected operational metrics. Preserve distinctions between process response, dependency readiness, Worker responsiveness, configured capabilities and demonstrated connectivity.
- **Verification and acceptance:** prefer deterministic offline and existing integration tests for status/timeout/failure, redaction, correlation and bounded metric behavior. Report actual coverage and unexecuted role checks separately; no paid Provider probes by default.
- **Boundary/dependencies:** reuse A2 safe configuration/errors and A3 source contracts; an unavailable production build is not proof of actual image identity. A6 governs diagnostic exposure. No separate monitoring-platform deployment is required; actual isolated runtime checks need explicit authorization.

### Revised Atomic 5 — Reliability & Recovery

- **Objective:** harden and verify existing workflow/index recovery and graceful resource shutdown without replacing the durability architecture.
- **Reuse and scope:** checkpoint/resume; claim, lease and fencing semantics; duplicate-delivery handling; workflow recovery; knowledge indexing recovery; task-local engine/client disposal; targeted failure injection; private-media consistency and existing safe reconciliation boundaries. Preserve distinct workflow/index heartbeat and generation contracts, and external-effect limitations.
- **Verification and acceptance:** prioritize deterministic tests and existing integration evidence for committed-state recovery, stale-write rejection, duplicate handling, checkpoint resume, failed reindex preserving the old generation, shutdown and private-media consistency. Do not claim real PostgreSQL concurrency/durability solely from mocks.
- **Documentation and boundary:** provide clear backup/restore instructions and limitations, including DB/media consistency and any unmeasured RPO/RTO. A full production disaster-recovery drill is no longer mandatory; unexecuted restores stay NOT RUN. Reuse A2–A4 contracts/evidence, with A6 access protection. No new recovery framework, production interruption or media deletion is implied.

### Revised Atomic 6 — Security Hardening

- **Objective:** preserve authentication/RBAC correctness and protect configuration, logs, private data and resource boundaries.
- **Reuse and scope:** existing auth/RBAC, safe errors and redaction, private-media access/path boundaries, dockerignore/build-context protection, input/resource bounds, dependency/security checks, protected health/metrics and existing bounded Provider safeguards. Preserve secure-cookie defaults; do not weaken controls to obtain a demo.
- **Verification and acceptance:** retain deterministic/offline and relevant existing integration security cases, actual dependency findings/dispositions and explicit verification limits. A passing CI job alone does not establish that all vulnerabilities or runtime exposures are resolved.
- **Deployment boundary/dependencies:** document TLS/proxy/Cookie/CORS and deployment security limitations accurately, using A2–A5 contracts. Public DNS, real certificates, external reverse-proxy deployment and production firewall provisioning are not required. No networking changes, public exposure, security bypass or commercial calls are authorized by the roadmap.

### Revised Atomic 7 — Full-stack Integration & Demo

- **Objective:** portfolio-oriented functional integration and demonstration replaces mandatory production staging.
- **Demonstrable existing capabilities:** authentication; Workspace/RBAC; workflow creation/execution; Agent Runtime; Tool Platform/MCP; Durable Execution; HITL approval/resume; Execution Trace; background execution; knowledge document upload/index/search; RAG/knowledge-assisted Agent workflows; and frontend interaction.
- **Reuse and verification:** use existing development infrastructure, deterministic fixtures and integration tests after the applicable A2–A6 work/reviews. A real local demonstration is desirable where the environment permits. Record artifact/config identities and run/job/scenario evidence appropriate to the layer actually tested, without exposing credentials.
- **Acceptance:** demonstrate supported capabilities with truthful scenario-level PASS/FAIL/BLOCKED/NOT RUN reporting, access-denial/recovery coverage where applicable and clear demo instructions. Browser HTTP mocks are not real connected workflows; backend-only E2E is not connected browser proof. Real workflow claims must follow actual operations through their dependencies.
- **Optional work and authorization:** production-style deployment, commercial Provider connectivity and previously blocked runtime checks remain optional, subject to explicit authorization/environment availability. A production restore drill is not a prerequisite. Resource lifecycle, private-data boundaries and any commercial budget require explicit scope; reuse infrastructure only when authorized.

### Revised Atomic 8 — Integration & Release

- **Objective:** integrate reviewed engineering hardening into a maintainer-controlled release with accurate evidence and limitations.
- **Mandatory scope/acceptance:** Final Source Review; required regressions; existing CI/security gates; accurate architecture/configuration/security/recovery documentation; demonstration instructions; release notes; version consistency; explicit unresolved evidence/limitations; and maintainer-controlled release publication.
- **Dependencies and evidence:** accept A1–A7 work under the revised criteria; resolve or explicitly disposition findings under maintainer review. Preserve the source-review → PR CI → approved merge → Main CI → local synchronization sequence and inspect actual results when authorized. Historical CI/tests cannot replace required new gates. Deferred production-runtime/restore evidence is not a default release blocker, and retains its actual status.
- **Release boundary:** actual commercial production deployment is not a release prerequisite. Do not claim production-certified or fully production-validated status. Proposed final title: **AgentForge v0.13.0 - Engineering Hardening**. Version metadata is unchanged in this documentation task; any later version alignment, tag or Release needs its own authorization.

### Shared amendment boundaries and current handoff

Retain the original architectural non-goals, finding provenance and evidence-layer
distinctions. No architecture redesign, test weakening, skipped-check laundering or
security-gate bypass follows from the portfolio objective. Offline tests, browser
mocks, real backend PostgreSQL/Redis/Celery E2E, real connected demonstrations,
production Compose runtime, commercial Provider smoke and restore drills must be
reported separately. Optional production work still requires explicit permission;
this amendment does not reopen the blocked runtime plan.

Only `docs/v0.13/atomic3-deployment-infrastructure.md` and this roadmap change in
this task; all other existing implementation files remain byte-for-byte unchanged.
No version metadata, runtime resources, CI configuration or tests are changed.
No application regression rerun is required solely for this amendment; the 389-test
result remains historical. Atomic 3 awaits source review/integration; Final Source
Review PASS, runtime verification PASS and Atomic 3 COMPLETE are not declared.
Await ChatGPT Closeout Report Review.
