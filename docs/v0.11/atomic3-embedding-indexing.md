# Atomic 3: Embedding and Indexing

Atomic 3 turns successfully parsed Atomic 2 documents into durable, source-grounded vector
generations. It adds deterministic character chunking, an OpenAI-compatible embedding boundary,
PostgreSQL `vector(1536)` storage, a cosine HNSW index, durable Celery jobs, explicit index APIs,
and database-backed recovery. It does not add query embeddings, retrieval/top-k APIs, reranking,
RAG generation, workflow nodes, agent tools, or frontend indexing screens.

## Chunking and source locations

`ChunkingConfig` defaults to 1,000 Python characters, 150 characters of overlap, and at most 2,500
chunks. The maximum covers Atomic 2's 2,000,000-character input bound with the default 850-character
stride. Configuration rejects non-positive sizes and overlaps outside `0 <= overlap < chunk_size`.
Windows are deterministic; leading/trailing whitespace is removed while adjusting offsets, and an
all-whitespace window is not stored. For every result,
`parsed_content[start_offset:end_offset] == content`; offsets are Python Unicode character indexes,
not UTF-8 byte positions.

PDF page numbers come only from Atomic 2's persisted `parse_metadata["pages"]` ranges. A chunk that
intersects multiple ranges records the minimum and maximum page number. TXT, Markdown, and DOCX
chunks normally have null page fields. Indexing never reparses the original private file.

## Embedding provider

`EmbeddingProvider` exposes `model`, `dimensions`, and async `embed_documents(texts)`. Production
composition always constructs `OpenAIEmbeddingProvider`; deterministic fakes exist only in tests
and are never an automatic fallback. Defaults are:

- `EMBEDDING_MODEL=text-embedding-3-small`
- `EMBEDDING_DIMENSIONS=1536`
- `EMBEDDING_BATCH_SIZE=32`
- `EMBEDDING_REQUEST_TIMEOUT_SECONDS=30`
- `EMBEDDING_MAX_RETRIES=2`

`EMBEDDING_API_KEY` is required when a worker executes a job. `EMBEDDING_BASE_URL` may point to an
OpenAI-compatible service. Requests are sequential bounded batches; only rate limits, timeouts,
connection failures, and provider 5xx failures receive finite exponential-backoff retries. Counts,
dimensions, finite numeric values, and nonzero vectors are validated before persistence. Logs contain
job identifiers and safe error codes, never keys, document text, or vectors.

The database column is fixed at 1,536 dimensions. A different configured dimension fails closed with
`EMBEDDING_DIMENSIONS_INCOMPATIBLE`; changing dimensions requires a new migration and index rebuild,
not mixed writes. Model identity, dimensions, chunking version, and source digest are bound into each
job.

## PostgreSQL and pgvector

Migration `0045_create_knowledge_vector_index` follows `0044_create_knowledge_documents`, creates the
`vector` extension if absent, and adds:

- `knowledge_document_chunks`, with scoped document ownership, generation, exact source offsets,
  optional page range, content, model identity, and `vector(1536)` embedding;
- `knowledge_index_jobs`, with `pending/running/succeeded/failed` state, generation, source/config
  identity, attempt count, claim token, fencing generation, lease, safe error code, and timestamps;
- `knowledge_documents.active_index_generation_id`, the sole generation Atomic 4 may read.

Composite foreign keys prevent cross-workspace/base/document attachment. Document deletion cascades
to jobs and chunks. A generation/chunk ordinal is unique, one partial unique index permits only one
pending or running job per document, and scoped indexes support ownership queries. The embedding
column has a real HNSW index using `vector_cosine_ops`. Downgrade removes Atomic 3 tables and columns
but deliberately does not drop the possibly shared `vector` extension.

## Job lifecycle, claims, and recovery

`POST .../documents/{document_id}/index` requires `knowledge_edit`. It validates a `ready` document,
idempotently inserts one pending job, commits it, then publishes only the job UUID. A broker error does
not erase the committed job. `GET .../index` requires `knowledge_read` and returns job state, active
generation, effective chunk count/model/version, and only a safe error code. Scoped resource lookup
returns 404 for a mismatched workspace or knowledge base. No endpoint returns embeddings.

A worker uses a fresh `NullPool` engine. It atomically changes a pending job (or an expired running
job) to running, increments the fencing generation and attempt count, and commits a claim token and
lease. It then releases the session before reading/chunking/embedding. During remote embedding it
renews the lease through brief independent sessions without holding a connection between heartbeats.
Final persistence locks and revalidates the exact token, generation, and unexpired database-clock
lease. Duplicate Celery delivery
therefore yields `not_claimed`, while a recovered stale worker cannot overwrite its successor.

Celery Beat runs `agentforge.knowledge.index.recovery.scan`. Each bounded scan uses an independent
session and `FOR UPDATE SKIP LOCKED` to select pending or lease-expired jobs, commits dispatch timing,
releases locks, and then republishes IDs. Broker failures remain eligible after the configured delay.
The scan is a publisher; database claim/fencing remains the execution authority.

## Atomic reindex

An explicit request after success creates a new generation while the old generation stays active.
Chunking and remote embedding happen outside a database transaction. One final fenced transaction
writes the complete new generation, switches `active_index_generation_id`, removes old chunks, and
marks the job succeeded. Any embedding error, database rollback, process crash, deletion cascade, or
lost lease leaves the previous active generation unchanged. A failed job records only a stable error
code.

## Deployment and operations

Development, production Compose, and PostgreSQL CI services use the pinned image
`pgvector/pgvector:0.8.7-pg16-bookworm`. Before production rollout:

1. take and independently restore-test a logical and/or physical backup;
2. inventory the existing PostgreSQL 16 image, extensions, architecture, locale, and checksums;
3. rehearse the image change and `0044 -> 0045` migration against an isolated restored copy;
4. verify application reads, extension version, `vector(1536)`, HNSW index, and rollback procedure;
5. schedule writer quiescence and retain the untouched backup and prior image for rollback.

Do not run `docker compose down -v`. Do not assume an Alpine-created PostgreSQL data directory is safe
to mount directly into a Bookworm image merely because both advertise PostgreSQL 16. Use a supported,
tested migration/restore path for the actual deployment and never experiment on the only production
volume. The Alembic downgrade retains the extension and cannot by itself reverse an operating-system
image/data-directory migration.

Embedding APIs add external availability, rate-limit, privacy, latency, and per-token cost risk.
Operators should set provider quotas and alerts, keep source text out of logs, and monitor safe failure
codes and retry volume.

## Atomic 4 read contract

Atomic 4 may read only chunks whose `index_generation_id` equals the owning document's
`active_index_generation_id`. Its durable inputs are workspace ID, knowledge-base ID, document ID,
chunk ID/content, embedding and model, exact source offsets, page metadata, and active generation. A
succeeded historical job whose generation is no longer active is not retrieval-eligible.
