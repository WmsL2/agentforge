# v0.11 Atomic 1 — Knowledge Base Domain & Workspace RBAC

## Scope

Atomic 1 adds a durable, workspace-scoped Knowledge Base resource. It supports create,
list, detail, rename/description update, and delete operations. Document upload,
parsing, chunking, embeddings, vector storage, retrieval, Agent tools, Workflow
Knowledge nodes, and frontend UI are intentionally out of scope.

## Persistence

Migration `0043_create_knowledge_bases` creates `knowledge_bases` with UUID `id`,
required `workspace_id` and `name`, optional `description` and
`created_by_user_id`, plus timezone-aware timestamps. The workspace foreign key uses
`ON DELETE CASCADE`; the creator foreign key uses `ON DELETE SET NULL`.

`(workspace_id, name)` is unique, so names are unique only within one workspace. The
`(workspace_id, created_at, id)` index supports stable paginated workspace listings.

## Authorization

| Role | Read | Create | Edit | Delete |
| --- | --- | --- | --- | --- |
| Owner | Yes | Yes | Yes | Yes |
| Admin | Yes | Yes | Yes | Yes |
| Member | Yes | No | No | No |

Every service operation calls `WorkspaceAuthorizationService.require_permission`.
Non-members receive 404, while members without an operation permission receive 403.
Resource reads and mutations always use both `workspace_id` and knowledge-base ID.

## API

- `POST /api/v1/workspaces/{workspace_id}/knowledge-bases` — 201
- `GET /api/v1/workspaces/{workspace_id}/knowledge-bases` — 200, `{items, total}`
- `GET /api/v1/workspaces/{workspace_id}/knowledge-bases/{id}` — 200
- `PATCH /api/v1/workspaces/{workspace_id}/knowledge-bases/{id}` — 200
- `DELETE /api/v1/workspaces/{workspace_id}/knowledge-bases/{id}` — 204

The route obtains the authenticated user, the service applies authorization and
domain conflict mapping, and the repository performs workspace-scoped SQLAlchemy
operations. The request-level database dependency owns commit and rollback;
repositories only flush. PostgreSQL uniqueness races are mapped to HTTP 409.

## Verification

From `backend/`:

```bash
uv run ruff check app tests cli
uv run ruff format app tests cli --check
uv run ty check
uv run pytest tests/ -q
uv run alembic heads
uv run alembic upgrade head
uv run alembic current
$env:AGENTFORGE_RUN_POSTGRES_E2E="1"
uv run pytest tests/integration/knowledge/test_knowledge_postgres.py -v -rs
```

Migration downgrade/upgrade verification must use a dedicated disposable database:
upgrade to 0042, upgrade to head, downgrade to 0042, then upgrade to head again.
