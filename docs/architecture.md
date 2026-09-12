# Architecture Guide

This project follows a **Repository + Service** layered architecture. Most features — users,
conversations, files, RAG documents, and sync sources — use the same pattern:
**Models → Schemas → Repositories → Services → Endpoints**. The v0.2 Workflow Core adds
explicit Domain, Validation, and Execution layers to that foundation. v0.3
adds Agent Runtime Integration, v0.4 adds the Tool Platform, and v0.5 adds MCP
Integration & Tool Discovery without replacing the Repository + Service model.

## Request Flow

```
HTTP Request → API Route → Service → Repository → Database
                  ↓
              Response ← Service ← Repository ←
```

Routes never contain direct database calls. All data access goes through
services, which in turn delegate to repositories.

## Directory Structure (`backend/app/`)

| Directory / File | Purpose |
|-----------|---------|
| `api/routes/v1/` | HTTP endpoints, request validation, auth |
| `api/deps.py` | Dependency injection (db session, current user) |
| **`services/`** | **Business logic, orchestration** |
| ↳ `user.py` | User CRUD, profile updates |
| ↳ `conversation.py` | Conversation & message management |
| ↳ `file_upload.py` | Chat file upload handling |
| ↳ `file_storage.py` | File storage abstraction (local / S3) |
| **`repositories/`** | **Data access layer, database queries** |
| ↳ `user.py` | User queries |
| ↳ `conversation.py` | Conversation queries |
| ↳ `chat_file.py` | Chat file queries |
| **`schemas/`** | **Pydantic request/response models** |
| ↳ `user.py` | User schemas |
| ↳ `conversation.py` | Conversation & message schemas |
| ↳ `file.py` | File upload schemas |
| **`db/models/`** | **SQLAlchemy 2.0 models** |
| ↳ `user.py` | User model |
| ↳ `conversation.py` | Conversation & message models |
| ↳ `chat_file.py` | Chat file model |
| ↳ `webhook.py` | Webhook model |
| `core/config.py` | Settings via pydantic-settings |
| `core/security.py` | JWT / API key utilities |
| `agents/` | AI agents and tools |
| `commands/` | Django-style CLI commands |
| `worker/` | Background task definitions |

## Layer Responsibilities

### API Routes (`api/routes/v1/`)
- HTTP request/response handling
- Input validation via Pydantic schemas
- Authentication and authorization checks
- **Never** contains direct DB calls — always delegates to a service

### Services (`services/`)
- Business logic and validation
- Orchestrates one or more repository calls
- Raises domain exceptions (`NotFoundError`, `AlreadyExistsError`, etc.)
- Orchestrates business operations inside the request-scoped transaction

### Repositories (`repositories/`)
- Database operations only
- No business logic
- Uses `db.flush()` not `commit()` (the dependency-injected session manages transactions)
- Returns ORM rows or result objects needed by services

### Schemas (`schemas/`)
- Separate `Create`, `Update`, and `Response` models per entity
- `Response` schemas use `model_config = ConfigDict(from_attributes=True)` for ORM conversion

### Models (`db/models/`)
- SQLAlchemy 2.0 model definitions
- Relationships, indexes, and column defaults live here

## Workflow Core

The Workflow Core is not a conventional CRUD-only path. Its application services coordinate
domain objects, validation, deterministic execution, and persistence. See the detailed
[Workflow Core architecture](workflow-core.md).

## Agent Runtime Integration

The current platform combines the v0.2 Workflow Core, v0.3 Agent Runtime, v0.4
Tool Platform, and v0.5 MCP Integration & Tool Discovery. Workflow execution
uses the application-scoped registry created by `open_tool_platform()` in the
FastAPI lifespan; request dependencies compose `AgentRunner` instances against
that registry.

```text
HTTP -> WorkflowRunService -> WorkflowEngine -> DispatchingNodeExecutor
     -> AgentNodeExecutor -> AgentRunner -> LangGraphAgentRunner
```

For a tool-enabled Agent run, the runtime integration is:

```text
WorkflowEngine
  -> AgentNodeExecutor
  -> LangGraphAgentRunner
  -> model.bind_tools(StructuredTool)
  -> LLM AIMessage.tool_calls
  -> ToolNode
  -> LangGraphToolAdapter
  -> ToolExecutionRequest
  -> ToolExecutionService
  -> ToolRegistry / ToolSchemaValidator / ToolExecutor
```

## MCP Integration

MCP integration points toward the Tool Platform; the Tool Platform never
depends on MCP. In particular, `app.services.tool` contains no official SDK
types. The MCP boundary consists of framework-independent contracts,
`MCPSDKClientAdapter` and stdio transport, discovery/discovered-tool mapping,
`MCPToolExecutor`, registration/lifecycle services, and
`open_tool_platform()` composition.

At startup, `open_tool_platform()` creates `ToolRegistry`, registers native
tools, opens configured stdio MCP servers, discovers their tools, creates MCP
executors, and registers the resulting local definitions. FastAPI exposes the
shared registry through `request.state.tool_registry`. The `AsyncExitStack`
managed MCP clients remain alive while the app runs; shutdown closes them before
the lifespan then closes Redis and the database.

Agent binding is dynamic and remains directionally separate from MCP:

```text
registry.definitions()
  -> LangGraphToolAdapter
  -> StructuredTool[]
  -> LangGraphAgentRunner
  -> model.bind_tools()

ToolNode -> adapter -> ToolExecutionService -> ToolRegistry -> MCPToolExecutor
         -> MCPClient.call_tool() -> remote MCP server
```

The engine schedules validated nodes; the dispatcher selects the executor by
node kind. `START`, `VALUE`, and `END` remain deterministic, while `AGENT`
uses the runtime adapter. LangGraph is an agent-runtime implementation, not
the Workflow Engine. The Tool Platform Core is also not a LangChain Tool
Registry alias. See [Agent Runtime architecture](agent-runtime.md) and
[Tool Platform](tool-platform.md) for the detailed boundaries.

```
HTTP request
    |
    | FastAPI parses JSON into a Workflow Pydantic schema and resolves current_user + AsyncSession
    v
Route function
    |
    | passes workflow_id, user_id, and request data to a Workflow application-service instance
    v
WorkflowService or WorkflowRunService instance
    |
    | constructs WorkflowDefinition / WorkflowRun domain objects and invokes validation or execution
    v
WorkflowValidator or WorkflowEngine instance
    |
    | validates the DAG, schedules ready nodes, and delegates node work through NodeExecutor
    v
Workflow repository function
    |
    | maps persistence data to SQLAlchemy Workflow / WorkflowRun ORM objects and calls flush()
    v
Request-scoped AsyncSession instance
    |
    | sends SQL through asyncpg
    v
PostgreSQL workflows / workflow_runs tables
```

`get_db_session` owns request-level transaction handling: it commits when the request succeeds
and rolls back when an exception escapes. Services do not commit independently; repositories use
`flush()` so generated identifiers and state are available within the same transaction.

## Key Files

- Entry point: `app/main.py`
- Configuration: `app/core/config.py`
- Dependencies: `app/api/deps.py`
- Auth utilities: `app/core/security.py`
- Exception handlers: `app/api/exception_handlers.py`

## Authentication & Authorization

### Authentication Methods

The project supports two authentication methods, both always available:

1. **JWT (JSON Web Tokens)** -- Used by the frontend and API clients.
   - Login via `POST /api/v1/auth/login` returns `access_token` + `refresh_token`.
   - Access tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30 min).
   - Refresh tokens expire after `REFRESH_TOKEN_EXPIRE_MINUTES` (default 7 days).
   - The frontend stores tokens as HTTP-only cookies.
   - WebSocket auth passes the JWT as a query parameter (`?token=<jwt>`) or cookie.

2. **API Key** -- Used for server-to-server and programmatic access.
   - Passed via the `X-API-Key` header (configurable via `API_KEY_HEADER`).
   - A single shared key set via the `API_KEY` environment variable.
   - Uses constant-time comparison (`secrets.compare_digest`) to prevent timing attacks.

### Roles

Two roles are defined in `UserRole` (see `app/db/models/user.py`):

| Role | Value | Description |
|------|-------|-------------|
| **ADMIN** | `"admin"` | Full system access, can manage users, RAG, webhooks, exports |
| **USER** | `"user"` | Standard access: chat, profile, search |

Role hierarchy: `ADMIN` has access to everything. The `has_role()` method on the
User model returns `True` for any role if the user is an admin.

### How RoleChecker Works

`RoleChecker` is a callable FastAPI dependency class in `app/api/deps.py`:

```python
class RoleChecker:
    def __init__(self, required_role: UserRole) -> None:
        self.required_role = required_role

    async def __call__(self, user: User = Depends(get_current_user)) -> User:
        if not user.has_role(self.required_role):
            raise AuthorizationError(...)
        return user
```

Use it in routes:

```python
# Any authenticated user
@router.get("/profile")
async def profile(current_user: CurrentUser): ...

# Admin only
@router.get("/all-users")
async def list_users(current_user: CurrentAdmin): ...
```

The type aliases are:
- `CurrentUser` = `Annotated[User, Depends(get_current_user)]` -- any authenticated user
- `CurrentAdmin` = `Annotated[User, Depends(RoleChecker(UserRole.ADMIN))]` -- admin role required
- `CurrentSuperuser` = `Annotated[User, Depends(get_current_active_superuser)]` -- legacy alias for admin

### IDOR Protection

Conversation and file endpoints enforce ownership at the service layer:
- Conversations pass `user_id=current_user.id` to the service, which filters queries by owner.
- File downloads verify `chat_file.user_id == current_user.id` before returning the file.
- This prevents users from accessing resources belonging to other users.

For full endpoint-level permissions, see `docs/permissions.md`.

## File Processing in Chat

When a user uploads a file in the chat interface, the following pipeline executes:

```
Upload (POST /files/upload)
  -> Validate (MIME type + size)
  -> Classify (image / pdf / docx / text)
  -> Parse (extract text content)
  -> Store (save to media/{user_id}/)
  -> Record (create ChatFile in DB)
  -> Link (attach to message when sent)
```

### Supported File Types

| Category | Extensions | Processing |
|----------|-----------|------------|
| Images | JPEG, PNG, WebP, GIF | Stored as-is, sent to LLM as binary for vision |
| PDF | .pdf | Text extracted via configured parser |
| Documents | .docx | Text extracted via python-docx |
| Text | .txt, .md | UTF-8 decoded directly |

### Parser Selection
PDFs are parsed using PyMuPDF (fast, local, no API key needed).

### Storage

Files are saved to `media/{user_id}/` via `FileStorageService`. The `ChatFile`
model stores the `storage_path`, `filename`, `mime_type`, `size`, `file_type`,
and `parsed_content` (extracted text). Only the file owner can access their files.

### Size Limits

Maximum upload size is controlled by `MAX_UPLOAD_SIZE_MB` (default 50MB).
