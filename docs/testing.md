# Testing Guide

## Running Tests

```bash
cd backend

# Run ordinary backend tests (no required PostgreSQL E2E or paid provider request)
uv run pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/api/test_health.py -v

# Run specific test
pytest tests/api/test_health.py::test_health_check -v

# Run Tool Platform coverage
uv run pytest tests/tool -q
uv run pytest tests/api/tool -q

# Run Agent Runtime coverage
uv run pytest tests/agent_runtime -q

# Run Workflow, Agent Runtime, and Tool Platform coverage
uv run pytest tests/workflow tests/agent_runtime tests/tool tests/api/tool -q

# Run with verbose output
pytest -v

# Stop on first failure
pytest -x
```

## Test Structure

```
tests/
├── conftest.py          # Shared fixtures
├── api/                 # API endpoint tests
│   ├── test_health.py
│   └── test_auth.py
├── workflow/            # Workflow domain, validation, execution, and application tests
├── agent_runtime/       # Agent Runtime contracts and offline LangGraph runner tests
├── tool/                # Tool Platform contracts, validation, registry, and execution tests
├── api/workflow/        # Workflow API tests using ordinary test overrides
├── api/tool/            # Production Tool Platform dependency composition tests
└── integration/
    ├── workflow/        # Opt-in real PostgreSQL AGENT workflow E2E
    └── agent_runtime/   # Strict opt-in live compatible-provider smoke test
```

## Key Fixtures (`conftest.py`)

```python
# Database session for tests
@pytest.fixture
async def db_session():
    async with async_session() as session:
        yield session
        await session.rollback()

# Test client
@pytest.fixture
def client():
    return TestClient(app)

# Authenticated client
@pytest.fixture
async def auth_client(client, test_user):
    token = create_access_token(test_user.id)
    client.headers["Authorization"] = f"Bearer {token}"
    return client
```

## Writing Tests

### API Endpoint Test
```python
def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
```

### Service Test
```python
async def test_create_item(db_session):
    service = ItemService(db_session)
    item = await service.create(ItemCreate(name="Test"))
    assert item.name == "Test"
```

### Test with Authentication
```python
def test_protected_endpoint(auth_client):
    response = auth_client.get("/api/v1/users/me")
    assert response.status_code == 200
```

## Frontend Tests

```bash
cd frontend

# Run unit tests
bun test

# Run with watch mode
bun test --watch

# Run E2E tests
bun test:e2e

# Run E2E in headed mode (see browser)
bun test:e2e --headed
```

## Ordinary tests and opt-in integrations

Ordinary tests don't hit a real database. The `client` fixture in `tests/conftest.py` overrides
`get_db_session` with a mocked async session (`AsyncMock`) via FastAPI's
`app.dependency_overrides`, so the suite runs fast and needs no Postgres container:

- `mock_db_session` — an `AsyncMock` standing in for `AsyncSession` (`execute`, `commit`, `rollback`, `close`)
- Overrides are registered before each test and cleared afterwards
- Assert against the mock's calls, or stub `execute(...)` return values for the path under test

Ordinary API tests use mocked database dependencies where appropriate and do
not require PostgreSQL or a provider request. The integration tests are
explicitly opt-in:

```powershell
# Real PostgreSQL API -> service -> repository -> persistence E2E.
$env:AGENTFORGE_RUN_POSTGRES_E2E = "1"
uv run pytest tests/integration/workflow/test_agent_workflow_e2e.py -q
Remove-Item Env:AGENTFORGE_RUN_POSTGRES_E2E

# Real LangGraph -> configured OpenAI-compatible provider smoke test.
$env:AGENTFORGE_RUN_LIVE_AGENT_SMOKE = "1"
# Optional: $env:AGENTFORGE_LIVE_AGENT_MODEL = "<provider-model>"
uv run pytest tests/integration/agent_runtime/test_langgraph_live.py -q
Remove-Item Env:AGENTFORGE_RUN_LIVE_AGENT_SMOKE
```

The PostgreSQL E2E uses real PostgreSQL but replaces `AgentRunner` with a fake
at the external boundary. The live runtime smoke uses the real configured
provider and does not require PostgreSQL. Neither integration runs in the
normal suite unless its environment variable is set.
