# Atomic 7: Workflow Agent Knowledge Tool

## Goal and execution path

An AGENT node may opt into LangGraph tool calling against one knowledge base. Its existing `runner`, `instruction`, and optional `model` fields remain valid. When `knowledge_base_id` is absent, the original AGENT runner and output contract are unchanged.

```json
{
  "runner": "langgraph",
  "instruction": "Answer from the configured knowledge base.",
  "knowledge_base_id": "00000000-0000-0000-0000-000000000000"
}
```

`knowledge_base_id` must be a UUID string. Unknown fields, including `workspace_id` and `actor_user_id`, are rejected by workflow validation. The configured ID gives no authorization by itself.

## Isolation, authorization, and MCP

The executor takes workspace and actor IDs from the persisted run's trusted `NodeExecutionContext`. Historical runs without an actor fail closed. It preflights knowledge base access before creating the node runner. Every knowledge tool call invokes `KnowledgeRetrievalService.search`, which checks authorization again. Tool arguments expose only `query` and `top_k`; model output and metadata cannot select an identity or knowledge base.

Each enhanced node execution owns a ToolRegistry, ToolExecutionService, call limiter, evidence collector, and LangGraph runner. Existing native and MCP registrations are copied as definitions and base executors into the local registry; the shared registry is never mutated. A preexisting `knowledge_search` name causes a safe failure. The node runner closes its own model clients after success, error, or timeout. The task-level MCP client's lifecycle remains with the existing worker tool platform.

## Output and failure contract

When actual backend retrieval returns chunks, the output is JSON-compatible:

```json
{
  "answer": "Grounded answer",
  "status": "answered",
  "sources": [{
    "chunk_id": "UUID",
    "document_id": "UUID",
    "filename": "handbook.pdf",
    "page_start": 3,
    "page_end": 4,
    "similarity_score": 0.93
  }]
}
```

Sources come only from deduplicated backend retrieval items. Plain text and recognized text content blocks are accepted as answers. If the model never calls the tool, or retrieval yields no chunks, the node returns `status: "no_evidence"` with empty sources and a deterministic message. Unsupported response structures fail safely. The node uses the Knowledge Agent settings for an overall timeout and a default maximum of two searches. Provider, retrieval, and database errors are mapped to redacted AgentRuntimeError messages before Workflow failure persistence and trace recording.

Workflow RunStep, Checkpoint, and Approval Resume use existing schemas and durable engine behavior. A committed node output is restored without rerunning the node; an uncommitted node follows the existing recovery path. Resume retains the original submitter identity. No database migration is added; Alembic head remains `0046_add_workflow_run_actor_identity`.

## Verification and limits

Unit tests cover validation, evidence, safe errors, timeout, limiter, registry isolation, and concurrent execution. The dedicated PostgreSQL 16 + pgvector 0.8.7 CI job migrates an isolated database to 0046 and enforces JUnit `tests > 0`, `failures = 0`, `errors = 0`, and `skipped = 0`. Its E2E tests exercise LangGraph ToolNode, real retrieval and pgvector, committed output, replay protection, membership revocation, and cross-workspace denial. Local results and any unavailable PostgreSQL evidence are reported separately in the Atomic review report.

The feature does not add a visual editor, conversation memory, cross-base search, or new embedding and retrieval SQL implementations.
