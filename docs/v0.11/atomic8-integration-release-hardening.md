# Atomic 8: Knowledge integration and release hardening

This is local release preparation for v0.11.0. Version metadata and this document do not mean a tag or GitHub Release exists. The Alembic head remains `0046_add_workflow_run_actor_identity`; Atomic 8 adds no migration.

## Production path

An authenticated Workspace member creates a Knowledge Base, uploads a private TXT or PDF document, and submits indexing. The API commits a pending `KnowledgeIndexJob` before dispatching it to Redis. A Celery worker claims the job, chunks parsed content, requests 1536-dimensional embeddings, writes pgvector rows, and atomically switches the document's active index generation. Search reads only active chunks. A failed reindex leaves the previous generation active. Deletion removes the document and its indexed chunks; private stored files are removed through the document service.

There are three knowledge call modes:

1. Direct semantic search: `POST /api/v1/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/search` with `{"query":"grass carp growth","top_k":5}`.
2. Knowledge Agent: `POST /api/v1/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/ask` with `{"question":"What does the document say about growth?"}`. LangGraph calls the scoped `knowledge_search` tool, and sources come from actual retrieved chunks. `KNOWLEDGE_AGENT_ENABLED=true` enables this dedicated API only.
3. Workflow: an explicit `START → KNOWLEDGE → AGENT → END` graph passes retrieval output downstream, or an `AGENT` node with a configured `knowledge_base_id` calls `knowledge_search` itself. The latter does not depend on `KNOWLEDGE_AGENT_ENABLED`. The Workflow definition API accepts these backend graph nodes; the existing React Flow editor has no KNOWLEDGE node UI.

Create a base with `POST /api/v1/workspaces/{workspace_id}/knowledge-bases` and `{"name":"Handbook"}`. Upload with multipart `POST /api/v1/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/documents` using a `file` field. Submit `POST .../documents/{document_id}/index`; poll the returned job and search after `succeeded`. The API requires the normal bearer authentication and Workspace permissions. The uploaded file is parsed and stored privately; clients never receive its storage path or embedding vector.

## Deployment and recovery

Use PostgreSQL 16 with pgvector 0.8.7, Redis 7, the API, a Celery worker, and Celery Beat. Apply the existing migrations in order through 0046 with `agentforge db upgrade` or `uv run alembic upgrade head`. Development and production Compose files use pgvector-capable images and named PostgreSQL volumes. Keep database backups together with the private media directory. Verify that restored media paths and database document rows agree before enabling indexing. The Knowledge index recovery scanner and Workflow recovery scanner redispatch eligible committed work; duplicate delivery is guarded by claim and checkpoint contracts. Configure Worker and Beat against the same broker and database as the API, with separately secured credentials. Remove private media by the document deletion API and check orphan files during operational maintenance; do not clear the database volume as an upgrade step.

Set `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS=1536`, `EMBEDDING_API_KEY`, and optional `EMBEDDING_BASE_URL` for indexing and search. Set `LLM_PROVIDER`, `LLM_API_KEY`, and optional `LLM_BASE_URL` for Agent calls. The sample environment file also documents batch, timeout, retry, Redis, and Celery settings. Production secrets must come from the deployment secret store. The deterministic local HTTP provider in the opt-in CI test checks application wiring; it does not establish that a commercial model works.

## Trust and visibility

Workspace membership and KB scope are checked before retrieval and again in the final vector-read transaction. A revocation committed before the final check denies that read. Concurrent revocation after the check cannot retract data already read or persisted. Cross-Workspace KB IDs do not grant access. Workflow knowledge execution uses the persisted submitting actor, not model-provided identity; historical runs without an actor fail closed. An approver can differ from the submitting actor without replacing that actor on resume. Provider errors are redacted before Run/Trace persistence.

Workflow Run and Trace readers with Workspace `RUN_READ` can see persisted tool parameters and successful knowledge output, including retrieved text. Base MCP tools can still be available to an enhanced AGENT node; Workspace RBAC does not implement external-tool data-loss prevention. Retrieved evidence does not prove that the model's natural-language answer is factually correct.

Knowledge Agent runners now use a dedicated asynchronous HTTP client per model instance and close it within a bounded cleanup interval. This prevents one Celery task from closing the OpenAI client later reused by another task, as observed in the approval-resume lifecycle test. Ordinary AGENT runner construction retains its existing default client behavior. Cancellation propagates; cleanup does not create a detached background model call.

## Verification and staging smoke

The opt-in CI job uses an isolated PostgreSQL database, Redis DB 15, a unique Celery queue, real Worker process, and deterministic OpenAI-compatible HTTP fixture. It exercises API upload, indexing, pgvector retrieval, Knowledge Agent, both Workflow modes, approval with another user, duplicate delivery, failed and successful reindex, and deletion. JUnit requires a nonzero test count and zero failures, errors, and skips. Local service absence must be reported as **NOT RUN**, not as a passing E2E result.

For staging, apply migrations through 0046 and verify `SELECT extversion FROM pg_extension WHERE extname='vector'` returns `0.8.7`. Start API, worker, and Beat with production-like credentials. Create a temporary Workspace and member, upload a known TXT file, wait for a successful index, check direct search and both Agent paths, then inspect RunStep, TraceEvent, and Checkpoint for the same run. Pause an approval flow, approve it as a different authorized user, and verify the original actor remains attached. Revoke membership and confirm new retrieval is denied. Exercise a failed reindex and check that the previous generation stays active; then reindex successfully and delete the document and base. Run one separate smoke test with the intended commercial Embedding and LLM providers, and review provider-side costs, rate limits, and output quality.

## Limits

This work adds no Knowledge management frontend, document management frontend, React Flow KNOWLEDGE editor, multi-base search, memory, hybrid search, reranking, GraphRAG, new runtime, or full MCP permission/DLP platform. Completed-run duplicate delivery and unfinished-run checkpoint recovery are distinct guarantees; retain the existing Atomic 6/7 recovery E2E gates when promoting a release.
