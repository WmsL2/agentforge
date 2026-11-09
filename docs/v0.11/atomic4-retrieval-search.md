# Atomic 4: Retrieval and Search

Atomic 4 adds read-only semantic search over the durable pgvector generations created by Atomic 3.
It searches one explicitly addressed knowledge base and returns source-grounded chunks. It does not
generate an answer, call a chat model, rerank results, perform keyword/hybrid search, expose a
Workflow knowledge node, or add an Agent tool.

## API

`POST /api/v1/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/search`

Example request:

```json
{
  "query": "草鱼体重与体长的关系",
  "top_k": 5,
  "min_score": 0.2
}
```

`query` is trimmed, required, and limited to 2,000 characters. `top_k` defaults to 5 and is limited
to 1–20. `min_score` is optional and, when present, must be between -1 and 1. Clients cannot submit
an embedding vector or select an arbitrary model.

Example response:

```json
{
  "query": "草鱼体重与体长的关系",
  "results": [
    {
      "chunk_id": "cbb68269-1fd2-4a08-9406-4caab64e8ce6",
      "document_id": "555f3aaa-c1bd-4476-b985-d8b67114aee3",
      "knowledge_base_id": "aa507a23-f9ac-4f1b-92a7-e8ca8d158c92",
      "filename": "fish.pdf",
      "chunk_index": 2,
      "content": "匹配的来源片段",
      "start_offset": 1200,
      "end_offset": 1210,
      "page_start": 3,
      "page_end": 3,
      "similarity_score": 0.87
    }
  ],
  "total": 1,
  "embedding_model": "text-embedding-3-small"
}
```

Responses use `Cache-Control: private, no-store` and `Pragma: no-cache`. They never include raw
vectors, storage paths, API keys, provider exceptions, or complete document bodies.

## Authorization and execution lifecycle

The service first opens a short database session and requires the persisted Workspace
`knowledge_read` permission. OWNER, ADMIN, and MEMBER roles have this permission. Missing membership,
including a platform-level app admin without membership, is hidden as 404. The knowledge base is
then looked up by the pair `(workspace_id, knowledge_base_id)`, so a UUID belonging to another
workspace is also 404.

The same short preflight session reads active index model identities and is then closed. Only after
authorization, scoped resource lookup, and model compatibility succeed does the service construct
the production `OpenAIEmbeddingProvider` and call `embed_documents([query])`. No database connection
is held while the remote request is pending. The provider retains the Atomic 3 request timeout,
bounded retry, response-model check, count/dimension/finite/nonzero validation, and explicit API-key
failure. The request-scoped provider client is closed in a `finally` block.

A fresh short session performs the vector query. `KNOWLEDGE_RETRIEVAL_DB_TIMEOUT_MS` defaults to
5,000 ms and is applied as a transaction-local PostgreSQL `statement_timeout`. The search path is
read only and does not create jobs, parse documents, switch generations, or write retrieval state.

## Active generation and model compatibility

Eligibility is defined by the durable Atomic 3 contract, not by the newest job:

- the document is in the requested Workspace and knowledge base and has `parse_status = 'ready'`;
- `active_index_generation_id` is not null;
- the chunk generation equals that active generation;
- the matching `KnowledgeIndexJob` generation is `succeeded`;
- Job and Chunk ownership agree with the Document;
- Job model/dimensions and Chunk model match the configured query provider.

A pending or failed reindex does not hide the still-active old generation. After a successful switch,
historical generation chunks are ineligible even if retained temporarily. Document deletion cascades
to jobs/chunks and therefore removes it from search.

Model identity is as important as dimensions. Atomic 4 uses a fail-closed strategy: if any eligible
active generation in the addressed knowledge base has a model or dimension different from the
configured query provider, the request returns `409 KNOWLEDGE_INDEX_MODEL_INCOMPATIBLE` before an
external embedding call. It never silently mixes semantic spaces. A knowledge base with no eligible
active index returns an empty result without calling the provider.

## PostgreSQL query and score semantics

The repository calculates pgvector cosine distance with
`KnowledgeDocumentChunk.embedding.cosine_distance(query_vector)`, applies every ownership,
generation, state, and model predicate in SQL, orders by distance ascending, and only then applies
`LIMIT top_k`. A deterministic secondary order uses document ID, chunk index, and chunk ID.
`min_score` is translated into the SQL predicate `cosine_distance <= 1 - min_score`; filtering is
not performed after loading a global Top-K into Python.

The response score is `1 - cosine_distance`, which is cosine similarity and theoretically ranges
from -1 to 1. It is a geometric ranking signal, not a probability, answer correctness estimate, or
percentage confidence.

## HNSW filtering behavior and performance

Migration 0045 supplies a global HNSW index with `vector_cosine_ops`. PostgreSQL may choose that
index for nearest-neighbor ordering or a sequential scan for small/selective datasets. Filtered
approximate scans can otherwise discard globally close rows from other tenants before enough scoped
rows are found. Atomic 4 sets pgvector 0.8.7's transaction-local
`hnsw.iterative_scan = strict_order`, allowing the HNSW scan to continue after filtered rows while
preserving distance order.

Iterative scanning remains approximate and bounded by pgvector's scan limits; it does not guarantee
perfect recall for every distribution. Large deployments should inspect `EXPLAIN (ANALYZE, BUFFERS)`,
tenant cardinality, latency, and recall, then tune pgvector settings or consider partitioning and
partial-index strategies in a future migration. Atomic 4 does not load the full vector corpus into
Python and does not force HNSW when PostgreSQL estimates an exact scan is cheaper.

## Failures, privacy, and cost

Provider rate limits, timeouts, connection/5xx failures, missing API keys, invalid vectors, and model
mismatches return stable safe codes without exposing SDK details, request headers, keys, query text,
vectors, or source chunks in logs. Database query failures return
`KNOWLEDGE_RETRIEVAL_DATABASE_ERROR`. Operators should monitor provider latency, quota, cost, and safe
error-code rates. Search queries and matched content are sensitive and must not be added to access or
application logs.

## Test and CI coverage

Unit tests cover input bounds, query-vector validation, safe provider/database failures, permission
ordering, no-index behavior, model rejection, session separation, no-cache API responses, status
mapping, sensitive-field exclusion, and OpenAPI generation. The dedicated
`v011-atomic4-retrieval-postgres-e2e` job uses PostgreSQL 16 with
`pgvector/pgvector:0.8.7-pg16-bookworm`, frozen dependencies, an isolated database, Alembic Head 0045,
extension/version checks, and a JUnit guard that rejects zero tests, skips, failures, and errors.

Real PostgreSQL tests cover cosine SQL, multi-document Top-K, score thresholds, Chinese queries,
Workspace and knowledge-base isolation, OWNER/ADMIN/MEMBER access, outsider hiding, empty indexes,
deletion cascade, failed and successful reindex behavior, old-generation exclusion, model identity,
independent-session persistence, filtered candidate sets, and an HNSW query-plan check.

Future Atomics may call `KnowledgeRetrievalService` from Workflow nodes or Agent tools, but must retain
the same authorization and tenant-scoped SQL boundary. This Atomic returns retrieved evidence only;
there is currently no RAG answer generation.
