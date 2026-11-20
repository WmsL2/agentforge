# v0.12 Atomic 3 — Document Management

## 1. Baseline and scope

- Verified initial clean worktree, branch `main`, HEAD `c9397015c8a257e232abb2cbdd8a3ef66a690db0`.
- User-supplied release evidence: Atomic 2 complete, PR #32 merged, Main CI #179 successful (16/16), 450 frontend unit tests and 26 Playwright E2E. These are baseline evidence, not CI results for these uncommitted changes.
- Version remains 0.11.0. Local implementation only; no Git mutations or external publication.

## 2. Page and component structure

The existing localized Knowledge Base Detail route is retained. `knowledge-base-detail.tsx` mounts document management only after a successful, matching base read, beneath the existing metadata and edit/delete controls. Workspace and membership freshness gates remain in `KnowledgeManagement`.

- `knowledge-document-management.tsx`: scoped list, pagination and selection; upload/delete confirmation dialogs share a private write-dialog component.
- `knowledge-document-detail-dialog.tsx`: current metadata, opt-in text preview and original-file download.
- `knowledge-document-utils.ts`: bounded client file validation, allowlisted error translations, scope matching, safe filename and browser download helper.
- English and Polish messages live under `knowledgeManagement.documents` with matching keys.

## 3. API and Hook chain

UI → existing `useKnowledgeDocuments`, `useKnowledgeDocument`, `useKnowledgeDocumentContent`, `useKnowledgeDocumentMutations` → `knowledgeApi` → guarded `apiClient` → same-origin route handlers → existing backend.

Upload calls `upload.mutateAsync(file)`, delete calls `remove.mutateAsync(documentId)`, download calls `download.mutateAsync(documentId)`. No direct backend requests, second data layer, auth coordinator changes, or Atomic 1 data layer changes were introduced.

On document detail 404, a separate existing base Hook refetch confirms whether the base still exists. Confirmed base 404 clears only that base prefix. Single-document 404 does not revoke or clear the Workspace.

## 4. Upload validation and HTTP 201

Single file, nonempty, maximum 10 × 1024 × 1024 bytes inclusive. Case-insensitive extensions PDF, DOCX, TXT, MD and MARKDOWN. MIME mappings follow the actual backend parser. Only absent browser MIME is completed with the canonical MIME; this wraps the original file bytes and retains filename and lastModified. Nonempty incompatible MIME, including unsupported Markdown aliases, is explicitly rejected with a localized explanation.

The server remains responsible for signatures, safe archive expansion and actual content parsing. The form never sets multipart Content-Type/boundary. Pending UI describes uploading and synchronous parsing, uses a synchronous duplicate-submit lock, disables inputs and never shows fabricated progress. Failed HTTP/network requests retain the selected file for manual retry. No automatic POST retry or Index API request occurs.

HTTP 201 ready closes the form and refreshes the list using existing invalidation. HTTP 201 failed means saved: the list refreshes, selected input is cleared, a safe parse reason is shown, and the form no longer offers upload submission. The saved document remains readable as metadata and downloadable/deletable. Unknown parse states never enable preview.

## 5. List and pagination

Real backend `skip = page * 10`, `limit = 10`, and returned `total` drive pagination. Initial pending UI does not invent total=0. Loading, empty, error and retry states are provided. List rows show filename, MIME, byte size, parse status, page count when supplied, created date and authorized actions. Wrong-scope rows are omitted. Filenames and all metadata render as plain React text.

A keyed base/workspace mount resets page and dialogs. Successful deletion of the last row on the last page moves to a valid previous page; returned total also clamps pagination. No index, chunk or embedding state is fabricated.

## 6. Metadata and preview

Opening the detail dialog requests current metadata rather than trusting the list row. Returned id, workspace_id and knowledge_base_id must match. Metadata includes filename, id, MIME, size, SHA-256, parse status/reason, optional page count and dates. Only finite numeric paragraph_count, table_count and table_cell_count from known parser output are exposed; arbitrary paths, stack traces and unknown server fields are omitted.

Content is requested only after explicit Preview, and only while current verified metadata is ready. Response document_id must match. Preview renders inert text in a scrolling pre element, with a 50,000 UTF-16-code-unit cap and explicit partial-preview notice. HTML, Markdown, scripts and external resource references are never interpreted or loaded. Closing preview cancels its query; unmount plus the existing gcTime=0 policy removes unused content. 409 maps to content unavailable, without Workspace cleanup.

## 7. Binary download and Object URL lifecycle

Download is offered after current metadata verification and uses the existing protected binary mutation. Original Blob bytes pass unchanged to URL.createObjectURL. Filename comes exclusively from verified current metadata; Content-Disposition parsing is intentionally unnecessary. Unicode is retained while path separators, unsafe filename punctuation, controls and bidi override characters are sanitized, with a bounded fallback name.

A temporary hidden anchor has the download attribute and is removed in finally. Object URL is revoked after 1 second, allowing browser consumption of the click. Repeated downloads use the existing latest-wins operation plus a UI sequence check. Before triggering, the component checks identity/mount lease, synchronous resource lease, operation sequence and current document query status/scope. No window.open, iframe, persistent Blob cache or public storage URL is used.

## 8. Delete and RBAC

Owner/admin may upload and delete. Members may read metadata/content and download. These privileges derive only from the existing freshly verified membership; app admin and creator fields are irrelevant. Pending/failed/revoked membership gates unmount the subtree. List errors also suppress write actions.

Delete requires a confirmation with the actual filename and warning covering parsed content and related index data. Cancel performs no write. HTTP 204 uses existing exact document-prefix cancellation/removal and list invalidation; the UI scope listener closes corresponding detail/preview/delete selection immediately. Other documents, bases and workspaces are retained. Normal errors, including a single-document DELETE 404, preserve confirmation and selected upload input; 403 closes the write dialog and revalidates membership.

## 9. Lifecycle isolation

Existing parent keys isolate workspace/base and authentication generation/epoch, including logout and same-user re-login. The existing `useKnowledgeLease` prevents callbacks after unmount or identity change. Local synchronous `onKnowledgeClear` listeners additionally invalidate resource leases before React unmount; base/workspace cleanup blocks all old callbacks, and document cleanup closes that selected document and suppresses downloads. Existing Hook cancellation and guarded facade validate request identity before/after HTTP.

Closing or switching a dialog unmounts its file/content/download operations. Old upload results cannot close a new dialog, show an old error, or navigate. Downloads cannot trigger after dialog close, scope switch, document deletion, revoked Workspace or account transition. Cancellation cannot undo a server-accepted upload or revoke a file already downloaded.

## 10. Error handling

Read the complete actual `backend/app/services/knowledge/document_parser.py` and relevant document service before implementation. Allowlist translations cover DOCUMENT_EMPTY, DOCUMENT_TOO_LARGE, DOCUMENT_TYPE_UNSUPPORTED, DOCUMENT_MIME_MISMATCH, DOCUMENT_SIGNATURE_MISMATCH, DOCX_ARCHIVE_LIMIT, DOCUMENT_CONTENT_UNAVAILABLE, DOCUMENT_PARSE_TIMEOUT, PDF_CORRUPT, PDF_ENCRYPTED, PDF_PAGE_LIMIT_EXCEEDED, PDF_NO_EXTRACTABLE_TEXT, PDF_PARSE_FAILED, DOCX_PARSE_FAILED, DOCX_NO_EXTRACTABLE_TEXT, DOCUMENT_TEXT_LIMIT_EXCEEDED and the additional actual parser code TEXT_NOT_UTF8.

Request errors and saved parse_error_code are handled separately. Existing safe status handling covers 401/403/404/422; document handling adds 400/413; preview 409 specifically means content unavailable, while other unknown 409 responses keep the existing conflict message. Unknown errors, 5xx and network errors use generic safe messages. Raw backend message/detail, private paths, tokens and stack traces are never rendered. AbortError is suppressed.

## 11. Tests and verification

The new component tests exercise real QueryClient, Knowledge Hooks, Auth Store and API facade with delayed HTTP responses. Original 450 tests are preserved; the existing Knowledge management HTTP fixture was extended by one line to answer the newly mounted document list using its actual wire schema.

Coverage includes scope admission, pagination and last-row delete, list retry, all allowed formats, empty/oversize/exact-limit/MIME handling, real multipart body, duplicate submit, 201 ready/failed, retained input on errors, safe translations for all real parser codes, fresh metadata and scope rejection, explicit bounded inert preview, unavailable/mismatched content, binary bytes/Unicode filenames/URL cleanup, error and late-download suppression, latest-wins, precise delete cache cleanup, role gates/revalidation, actual workspace/base changes, logout/account/same-user transitions and old callback isolation.

Final executed results are recorded in section 13. No thresholds, old assertions, dependency versions or CI configuration are weakened.

## 12. Known limitations and deferred features

- Docker Desktop is user-closed: no start/resume, container creation or Atomic 2 temporary-container modification/removal was attempted. No backend, PostgreSQL, Redis or Celery services were started. No WSL or Linux environment was installed.
- Linux Node 24 validation and real browser/backend integration are not executed for this Atomic; await GitHub CI and later integration gates. Baseline 26 E2E results do not validate this local diff.
- No real browser visual/mobile verification or actual OS download was performed; DOM anchor/Blob behavior is tested under jsdom. Browser filename adjustment and download permission behavior remain browser-controlled.
- Preview renders at most 50,000 code units; the existing API still transfers the full permitted content response (up to the backend 2 million character limit). This is a render bound, not server-side content pagination.
- Permissions update when existing membership/workspace requests revalidate; there is no real-time revocation subscription. Backend remains the final authorization boundary.
- Client checks cannot revoke server-accepted uploads/deletes or already obtained files. Parser/encoding failures remain saved, with no UI reparse or OCR.
- Index management/polling, embedding/chunks, search/ask, Workflow knowledge node, edit/reparse, OCR, batch upload and Atomic 4 remain deferred. No backend, database, dependency, version or CI change.


## 13. Executed final verification (Windows)

Runtime: Windows, Node v22.13.0, Bun 1.3.14, Next.js 15.5.23.

| Command (frontend working directory) | Actual result |
| --- | --- |
| `bun install --frozen-lockfile` | PASS, exit 0, 839 installs checked across 950 packages, no dependency changes. Existing Husky prepare message: `.git can’t be found`. |
| `bun run lint` | PASS, exit 0, 0 errors / 13 existing warnings; no new document-code warnings. |
| `bun run type-check` | PASS, exit 0. |
| `bun run test:run` | PASS, 537 tests / 29 files: original 450 + 87 new document tests. |
| `bun run test:coverage` | PASS, 537 tests / 29 files, original coverage thresholds unchanged. |
| `bun run build` | PASS, exit 0. Existing runtime config deprecation warnings remain. |
| `bun run test:run -- src/components/knowledge/knowledge-document-management.test.tsx` | PASS, 87 tests / 1 file. |
| `git diff --check` (repository root) | PASS. |
| Linux Node 24 / real browser-backend integration / Playwright E2E | NOT RUN for this local diff. |

Configured coverage remains restricted to the existing four files (`auth-cookies.ts`, `utils.ts`, `auth-store.ts`, `button.tsx`). Aggregate statements/lines 69.23%, branches 100%, functions 60.86%; these are not coverage percentages for the new document UI. Thresholds remain statements 50, branches 90, functions 40, lines 50. Original authentication races, Workspace/Workflow tests and multipart/binary assertions all remain in the successful full suite.

Raw local logs (ignored, not committed): `frontend/node_modules/.cache/atomic3-{lint,type-check,test-run,test-coverage,build,target}.log`.

Final change inventory: five new files (three implementation files, one component-test file, this document); four modified files (base-detail integration, existing test HTTP fixture, en/pl translations). Backend, migrations, auth coordination, Knowledge data layer, dependencies/lockfiles, CI and version surfaces are unchanged.

Final branch/HEAD remain `main` / `c9397015c8a257e232abb2cbdd8a3ef66a690db0`. All changes are local and unstaged. No branch creation/switch, add, commit, push, merge, reset, stash, PR, tag or release occurred. Atomic 4 was not started. Awaiting ChatGPT review.
