# Atomic 2: Document Management and Parsing

Atomic 2 adds private, workspace-scoped source documents to the v0.11 knowledge base. It does not add chunking, embeddings, retrieval, or vector storage.

## API

The authenticated endpoints live below:

`/api/v1/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/documents`

- `POST /` uploads one PDF, DOCX, TXT, or Markdown file and returns `201` metadata.
- `GET /` lists metadata with `skip` and `limit` pagination.
- `GET /{document_id}` returns metadata.
- `GET /{document_id}/content` returns extracted text for `ready` documents.
- `GET /{document_id}/download` returns the original private file as an attachment.
- `DELETE /{document_id}` removes the database row and then the private file.

Read operations require `knowledge_read`. Upload and delete require `knowledge_edit`. Every lookup includes workspace, knowledge-base, and document identifiers; a resource outside that scope is returned as not found. Responses never expose `storage_path`.

## Validation and parsing

Uploads are read with a strict `10 MiB + 1 byte` bound. The service rejects empty files, unsupported extensions, extension/MIME mismatches, invalid magic signatures, and unsafe DOCX ZIP expansion before storage. PDF parsing is limited to 200 pages and extracted text is limited to 2,000,000 characters. Parsing runs in a bounded worker-thread section so PyMuPDF and python-docx do not block the event loop.

PyMuPDF extracts PDF text and page offset metadata. python-docx extracts paragraphs and table rows. TXT and Markdown require UTF-8. Corrupt, encrypted, non-UTF-8, text-limit, and image-only PDF outcomes are persisted with `parse_status=failed` and a stable `parse_error_code`; `/content` returns `409`, while the original remains available to authorized users.

## Storage and consistency

Originals are stored below `MEDIA_DIR/knowledge` using server-generated workspace, knowledge-base, and document UUID components plus a sanitized basename. Storage rejects traversal, symlink escapes, and replacement of an existing path. Files are private and download responses use attachment disposition, `Cache-Control: private, no-store`, and `X-Content-Type-Options: nosniff`.

Upload owns its commit boundary because it must remove the already-written file if database flush or commit fails. A process crash can still occur between filesystem and database operations. `KnowledgeDocumentService.reconcile_orphans()` is the recovery primitive: it compares database storage keys with regular files below the private root and removes only unreferenced files. This also recovers files orphaned by database-level knowledge-base or workspace cascades. Symlinks are never followed or removed by reconciliation. Reconciliation is a maintenance operation and must run while document mutations are quiescent so it cannot race an upload between file creation and row commit.

Delete commits the inaccessible database state before file cleanup. A cleanup failure is logged without exposing the file through the API; reconciliation removes the private residue later. Duplicate uploads are allowed and always receive distinct server-generated document IDs and storage keys.

## Database

Migration `0044_create_knowledge_documents` follows `0043_create_knowledge_bases`. A composite foreign key from `(workspace_id, knowledge_base_id)` to the matching knowledge-base pair prevents cross-workspace attachment. Knowledge-base deletion cascades to document rows, creator deletion sets `created_by_user_id` to null, parse status has a database check, and scoped listing has a `(workspace_id, knowledge_base_id, created_at, id)` index.

The dedicated CI job migrates `0043 -> 0044 -> 0043 -> head`, runs the real PostgreSQL document suite, writes JUnit XML, and fails if the suite reports zero tests or any failure, error, or skip.

## Validation and next-stage boundary

Local Atomic 2 validation covers parser edge cases, storage escape prevention, service compensation, all six HTTP routes, real PostgreSQL constraints/cascades, independent-session durability, the reversible migration cycle, frozen dependency installation, and a production Docker build. The general test suite still skips opt-in external and PostgreSQL groups unless their dedicated environment gates are enabled; the Atomic 2 PostgreSQL group is run separately with no skips.

Atomic 3 may consume only rows with `parse_status=ready`. Its input is `parsed_content` together with `page_count` and `parse_metadata` page offsets, allowing future chunks to retain source locations. Atomic 2 deliberately creates no chunks, embeddings, vector index, retrieval API, workflow node, or agent tool.
