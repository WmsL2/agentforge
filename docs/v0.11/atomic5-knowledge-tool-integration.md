# Atomic 5: Knowledge Tool Integration

Atomic 5 adds one authenticated, stateless question-answering endpoint over an explicitly addressed
Workspace knowledge base:

`POST /api/v1/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/ask`

The request body contains only `question` (1–2,000 characters). The final review tightened the
previously published 4,000-character upper bound to align with the retrieval query contract. The
response contains `answer`,
`status` (`answered` or `no_evidence`), and backend-generated `sources`. Responses use
`Cache-Control: private, no-store` and `Pragma: no-cache`.

## Trust and authorization boundary

`KNOWLEDGE_AGENT_ENABLED` defaults to `false`. When enabled, `LLM_API_KEY` and the existing
embedding configuration must be present. The service checks Workspace `knowledge_read` permission
and the Workspace/knowledge-base pair before invoking a chat model. Atomic 4 then repeats that check
inside every `knowledge_search` execution, so membership revocation is observed between preflight
and tool use.

Every HTTP request creates its own `ToolRegistry`, `ToolExecutionService`, evidence collector, call
limiter, and LangGraph runner. `knowledge_search` is never added to the application-scoped registry
used by Workflow Agent nodes. The model-visible schema exposes only `query` and `top_k` (1–5).
Workspace ID, knowledge-base ID, and actor ID are captured by the executor from trusted HTTP context;
model arguments and tool metadata cannot select or override them.

## Evidence behavior

The agent instruction requires `knowledge_search`, treats retrieved text as untrusted data, and
forbids following document instructions, using outside knowledge, revealing secrets, or fabricating
citations. Source records are collected from successful backend retrieval calls, never parsed from
model output. If the model does not call the tool, or retrieval returns no chunks, the backend
discards the model answer and returns deterministic `no_evidence` with an empty source list.

The per-request call limit defaults to two and is reserved under an async lock, including concurrent
tool calls. LangGraph also receives a bounded recursion limit. The whole request flow has a
60-second default timeout, including authorization preflight, request-scoped composition, agent and
tool execution, response construction, and resource cleanup. Request-scoped model clients are
explicitly closed after success, failure, or cancellation. Tool/provider/runtime failures are mapped
to stable safe errors; queries,
document content, credentials, connection strings, and raw provider exceptions are not logged or
returned. The endpoint does not create a conversation, session, message, retrieval record, or index
job.

## Configuration

```dotenv
KNOWLEDGE_AGENT_ENABLED=false
KNOWLEDGE_AGENT_TIMEOUT_SECONDS=60
KNOWLEDGE_AGENT_MAX_TOOL_CALLS=2
LLM_API_KEY=
LLM_BASE_URL=
AI_MODEL=gpt-5.5
```

`LLM_BASE_URL` may select an OpenAI-compatible provider. Operators remain responsible for provider
privacy, residency, retention, latency, quota, and cost. Enabling this feature sends the user's
question and retrieved chunks to that configured provider.

## Verification

Unit and API tests cover schema hardening, authentication, configuration gating, preflight ordering,
scope forgery, safe failures, prompt-injection instructions, no-tool/empty-evidence behavior,
backend-only sources, request isolation, and the atomic concurrent call limit.
Structured model content is accepted only from standard `text` blocks; reasoning, tool-call, image,
unknown, and malformed content cannot become an answer. Timeout tests cover blocked authorization,
blocked agent execution, cancellation, cleanup, permission propagation, and concurrent request
isolation.

The `v011-atomic5-knowledge-agent-postgres-e2e` CI job uses PostgreSQL 16 with pgvector 0.8.7,
frozen dependencies, Alembic Head 0045, a fake deterministic embedding provider and fake chat model,
but the real Tool Platform, LangGraph, Atomic 4 retrieval service, PostgreSQL authorization, and
pgvector query. It verifies concurrent request isolation, current-generation selection, membership
revocation before LLM execution, cross-Workspace exclusion, and absence of retrieval/index writes.
Its JUnit guard rejects zero tests, failures, errors, or skips.

These tests do not claim live-provider validation. A staging smoke test with approved credentials is
still required before enabling the feature in a deployed environment.
