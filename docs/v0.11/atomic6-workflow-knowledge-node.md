# Atomic 6 — Workflow Knowledge Node

Atomic 6 adds a durable `knowledge` workflow node. The node performs authorized semantic retrieval only; answer generation remains the responsibility of a following `agent` node.

## Configuration

Literal query:

```json
{
  "knowledge_base_id": "00000000-0000-0000-0000-000000000000",
  "query_source": "literal",
  "query": "What evidence is available?",
  "top_k": 5
}
```

Workflow-input query:

```json
{
  "knowledge_base_id": "00000000-0000-0000-0000-000000000000",
  "query_source": "workflow_input",
  "input_key": "question",
  "top_k": 5
}
```

The modes are mutually exclusive. `top_k` defaults to 5 and is limited to 1–5. Queries must contain 1–2,000 characters. Dynamic lookup reads one top-level workflow-input key. Identity fields such as `workspace_id` and `actor_user_id` are rejected from node configuration.

## Output

The node returns JSON-persistable evidence:

```json
{
  "query": "What evidence is available?",
  "total": 1,
  "results": [
    {
      "chunk_id": "UUID",
      "document_id": "UUID",
      "filename": "source.pdf",
      "content": "Retrieved text",
      "page_start": 2,
      "page_end": 2,
      "similarity_score": 0.92
    }
  ]
}
```

Empty retrieval is a successful result with `total: 0`. Embeddings, internal storage paths, database details, credentials, and raw provider exceptions are never included.

## Trusted run identity

The authenticated submitter is copied by the synchronous or asynchronous application service into `workflow_runs.actor_user_id`. Migration `0046_add_workflow_run_actor_identity` adds the nullable user foreign key with `ON DELETE SET NULL`, preserving historical runs.

Workspace identity is never accepted from input, metadata, node configuration, or a Celery job. It is loaded from the persisted Workflow resource. The engine snapshots both values into an immutable `NodeExecutionContext` for each node. Historical runs with no actor continue to execute ordinary nodes, but a `knowledge` node fails closed.

## Execution and recovery

The HTTP synchronous runtime and per-task Celery composition root both register `KnowledgeNodeExecutor`. Async submission stores only the run ID in the job. Background execution, expired-lease recovery, synchronous approval continuation, and async approval redispatch reconstruct the original actor from the run and the workspace from the Workflow row.

Successful knowledge output is committed with the normal run state and checkpoint. Recovery resumes after committed nodes, so an already committed retrieval is not repeated. A retrieval that was not checkpointed follows the existing recovery contract.

`KnowledgeRetrievalService` opens independent short-lived sessions and rechecks `KNOWLEDGE_READ` on every retrieval. Membership removal before a later or resumed retrieval therefore denies access.

## Privacy and visibility

Knowledge text persisted in run outputs, checkpoints, and trace-adjacent workflow state is protected by the existing Workspace-scoped `RUN_READ` authorization used for run, checkpoint-derived output, and trace APIs. The node does not place trusted identity or evidence into user-controlled Workflow metadata.

## Limits

- No frontend React Flow node is included.
- No new vector SQL, embedding implementation, reranker, hybrid search, GraphRAG, or MCP server is added.
- The node does not call an LLM.
- A deleted or cross-Workspace Knowledge Base is hidden by the existing retrieval authorization boundary.
- Provider and database failures are persisted only as a stable, redacted workflow-node error.
