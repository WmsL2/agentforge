# AgentForge v0.11.0 release preparation

**Status: not released.** This file is a review checklist; version metadata does not create a tag, GitHub Release, or deployment. Consult repository tags and Releases for publication status.

## Scope

v0.11 adds Workspace-scoped Knowledge Bases and private document upload, parsing and management; chunking and pgvector indexing with durable Celery jobs and recovery; semantic search; a LangGraph Knowledge Agent API; an explicit Workflow KNOWLEDGE node; and an AGENT node that can call a scoped knowledge tool. Workflow runs retain their trusted submitting actor across durable execution and approval resume. Backend APIs implement these paths; there is no Knowledge management frontend or React Flow KNOWLEDGE editor.

The data path is Knowledge Base → Document → parsed text → Chunk → 1536-dimensional Embedding → active pgvector index generation → Retrieval. Read [Atomic 8 integration guide](v0.11/atomic8-integration-release-hardening.md) for API examples, three call modes, security boundaries, deployment settings, backup and recovery, and staging smoke steps. Atomic 1–7 design notes remain in `docs/v0.11/`.

## Upgrade requirements

- PostgreSQL 16 with pgvector 0.8.7; preserve the existing PostgreSQL and private media volumes. Back up both before migration.
- Apply the 0043 → 0044 → 0045 → `0046_add_workflow_run_actor_identity` Alembic chain. Atomic 8 itself adds no schema revision.
- Redis 7, API, Celery Worker, and Beat must share their intended broker/database configuration. Isolate test broker databases and queues from production.
- Configure `EMBEDDING_*` for indexing/retrieval and `LLM_*` for Agent calls. `KNOWLEDGE_AGENT_ENABLED` gates the dedicated Knowledge Agent API, not Workflow AGENT knowledge composition.
- Review Workspace roles and historical Workflow runs without actor identity. Knowledge execution for a historical actorless run fails closed.

## Release checklist

1. Confirm backend distribution, `app.__version__`, FastAPI, CLI, frontend package, and lock metadata all report `0.11.0`.
2. Run frozen backend/frontend installation, Ruff, type check, full backend and frontend suites, build, and `pip-audit` without vulnerability exceptions.
3. Run real PostgreSQL 16/pgvector 0.8.7, Redis 7, and Celery CI jobs with zero failures, errors, and skips. Check migration head and vector extension version in the same isolated database.
4. Execute the staging smoke in the Atomic 8 guide, including a real provider check, RBAC revocation, async Workflow, approval with a different user, reindex, deletion, and restore drill.
5. Review persistent Run/Trace visibility, available MCP tools, private file retention, backup coverage, and operational alerts. Retrieved sources are evidence references, not factual certification of generated prose.
6. Only after review and promotion, have an authorized maintainer create any release branch, tag, GitHub Release, or production deployment. None is created by this task.

## Known limits

No multi-KB search, conversation memory, hybrid search, reranking, GraphRAG, Knowledge frontend, React Flow KNOWLEDGE editor, or general external-tool DLP is included. The CI deterministic provider verifies integration wiring, while commercial provider availability and answer quality require separate staging evidence.
