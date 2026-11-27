"""Health endpoint tests."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.api.routes.v1.health import get_readiness_redis
from app.core.config import settings
from app.main import app
from app.services.health import get_health_session_factory


@pytest.fixture(autouse=True)
def health_dependencies(mock_db_session, mock_redis):
    app.dependency_overrides[get_health_session_factory] = lambda: lambda: mock_db_session
    app.dependency_overrides[get_readiness_redis] = lambda: mock_redis
    yield
    app.dependency_overrides.pop(get_health_session_factory, None)
    app.dependency_overrides.pop(get_readiness_redis, None)


@pytest.mark.anyio
async def test_health_check(client: AsyncClient):
    """Test liveness probe."""
    response = await client.get(f"{settings.API_V1_STR}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.anyio
async def test_readiness_check(client: AsyncClient):
    """Test readiness probe with mocked dependencies."""
    response = await client.get(f"{settings.API_V1_STR}/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ready", "degraded"]
    assert "checks" in data


@pytest.mark.anyio
async def test_readiness_check_redis_healthy(client: AsyncClient, mock_redis):
    """Test readiness when Redis is healthy."""
    mock_redis.ping = AsyncMock(return_value=True)

    response = await client.get(f"{settings.API_V1_STR}/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["checks"]["redis"]["status"] == "healthy"
    assert "latency_ms" in data["checks"]["redis"]


@pytest.mark.anyio
async def test_readiness_check_redis_unhealthy(client: AsyncClient, mock_redis):
    """Test readiness when Redis is unhealthy."""
    mock_redis.ping = AsyncMock(side_effect=Exception("Connection failed"))

    response = await client.get(f"{settings.API_V1_STR}/ready")
    # Should return 503 when Redis is down
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["redis"]["status"] == "unhealthy"
    assert "error" in data["checks"]["redis"]


@pytest.mark.anyio
async def test_readiness_check_db_healthy(client: AsyncClient, mock_db_session):
    """Test readiness when database is healthy."""
    # Mock successful DB query
    mock_db_session.execute = AsyncMock()

    response = await client.get(f"{settings.API_V1_STR}/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["checks"]["database"]["status"] == "healthy"


@pytest.mark.anyio
async def test_readiness_check_db_unhealthy(client: AsyncClient, mock_db_session):
    """Test readiness when database is unhealthy."""
    mock_db_session.execute = AsyncMock(side_effect=Exception("DB connection failed"))

    response = await client.get(f"{settings.API_V1_STR}/ready")
    # Should return 503 when DB is down
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["database"]["status"] == "unhealthy"


@pytest.mark.anyio
async def test_readiness_uses_generic_llm_api_key_for_custom_provider(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "custom-provider")
    monkeypatch.setattr(settings, "LLM_API_KEY", "runtime-key")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")

    response = await client.get(f"{settings.API_V1_STR}/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["llm"] == {
        "status": "configured",
        "connectivity_checked": False,
    }


@pytest.mark.anyio
async def test_readiness_marks_llm_not_configured_when_generic_key_is_missing(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "custom-provider")
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "legacy-template-key")

    response = await client.get(f"{settings.API_V1_STR}/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["llm"] == {
        "status": "not_configured",
        "connectivity_checked": False,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("endpoint", ["/health/ready", "/ready"])
@pytest.mark.parametrize("failure", ["database", "redis", "redis_false"])
async def test_readiness_never_discloses_exception_secrets(
    client,
    mock_db_session,
    mock_redis,
    endpoint,
    failure,
    caplog,
):
    secret = "postgresql://synthetic-user:synthetic-secret-marker@private-host/db"
    if failure == "database":
        mock_db_session.execute = AsyncMock(side_effect=RuntimeError(secret))
        code = "DATABASE_CONNECTION_FAILED"
    elif failure == "redis":
        mock_redis.ping = AsyncMock(side_effect=RuntimeError(secret))
        code = "REDIS_CONNECTION_FAILED"
    else:
        mock_redis.ping = AsyncMock(return_value=False)
        code = "REDIS_PING_FAILED"
    response = await client.get(f"{settings.API_V1_STR}{endpoint}")
    assert response.status_code == 503
    service = "database" if failure == "database" else "redis"
    assert response.json()["checks"][service]["error"] == code
    assert response.json()[service] == response.json()["checks"][service]
    assert "synthetic-secret-marker" not in response.text + caplog.text
    assert "private-host" not in response.text + caplog.text


@pytest.mark.anyio
async def test_live_version_and_basic_have_no_dependencies(client, mock_db_session, mock_redis):
    from app import __version__

    assert (await client.get("/api/v1/health")).json()[
        "max_upload_size_mb"
    ] == settings.MAX_UPLOAD_SIZE_MB
    assert (await client.get("/api/v1/health/live")).json()["details"]["version"] == __version__
    mock_db_session.execute.assert_not_called()
    mock_redis.ping.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("endpoint", ["/health/ready", "/ready"])
@pytest.mark.parametrize(
    "failure",
    ["database_timeout", "redis_timeout", "acquire", "close", "close_timeout", "missing_redis"],
)
async def test_bounded_probe_failures(
    client, mock_db_session, mock_redis, monkeypatch, endpoint, failure
):
    import asyncio

    import app.services.health as health

    monkeypatch.setattr(health, "PROBE_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(health, "CLEANUP_TIMEOUT_SECONDS", 0.02)

    async def stalled(*args):
        await asyncio.sleep(10)

    if failure == "database_timeout":
        mock_db_session.execute.side_effect = stalled
    elif failure == "redis_timeout":
        mock_redis.ping.side_effect = stalled
    elif failure == "acquire":

        def broken():
            raise RuntimeError("synthetic-private-host:password=do-not-disclose")

        app.dependency_overrides[get_health_session_factory] = lambda: broken
    elif failure == "close":
        mock_db_session.close.side_effect = RuntimeError(
            "synthetic-private-host:password=do-not-disclose"
        )
    elif failure == "close_timeout":
        mock_db_session.close.side_effect = stalled
    elif failure == "missing_redis":
        app.dependency_overrides[get_readiness_redis] = lambda: None
    async with asyncio.timeout(0.5):
        response = await client.get("/api/v1" + endpoint)
    assert response.status_code == 503
    codes = {
        "database_timeout": "DATABASE_TIMEOUT",
        "redis_timeout": "REDIS_TIMEOUT",
        "acquire": "DATABASE_CONNECTION_FAILED",
        "close": "DATABASE_CLEANUP_FAILED",
        "close_timeout": "DATABASE_CLEANUP_TIMEOUT",
        "missing_redis": "REDIS_UNAVAILABLE",
    }
    key = "redis" if failure in ["redis_timeout", "missing_redis"] else "database"
    assert response.json()["checks"][key]["error"] == codes[failure]
    assert "synthetic-private-host" not in response.text
    mock_db_session.commit.assert_not_called()
    if failure != "acquire":
        mock_db_session.close.assert_awaited_once()


@pytest.mark.anyio
async def test_capabilities_are_configuration_only(client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "legacy-not-runtime")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "synthetic-embedding")
    monkeypatch.setattr(settings, "KNOWLEDGE_AGENT_ENABLED", True)
    data = (await client.get("/api/v1/health/ready")).json()["checks"]
    assert data["llm"]["status"] == "not_configured"
    assert data["embedding"]["status"] == "configured"
    assert data["knowledge_agent"] == {
        "status": "not_configured",
        "connectivity_checked": False,
        "enabled": True,
    }
    assert data["worker"]["status"] == "configured" and not data["worker"]["connectivity_checked"]


@pytest.mark.anyio
async def test_cancel_propagates_and_closes_session(mock_db_session):
    import asyncio

    from app.services.health import probe_database

    started = asyncio.Event()

    async def stalled(*args):
        started.set()
        await asyncio.sleep(10)

    mock_db_session.execute.side_effect = stalled
    task = asyncio.create_task(probe_database(lambda: mock_db_session))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    mock_db_session.close.assert_awaited_once()


@pytest.mark.anyio
async def test_readiness_does_not_call_providers_or_celery(client, monkeypatch, mock_db_session):
    from unittest.mock import Mock

    import httpx

    from app.worker.celery_app import celery_app

    forbidden = Mock(side_effect=AssertionError("No remote call authorized"))
    monkeypatch.setattr(celery_app.control, "ping", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    forbidden.assert_not_called()
    assert str(mock_db_session.execute.call_args.args[0]) == "SELECT 1"
    mock_db_session.commit.assert_not_called()
    mock_db_session.close.assert_awaited_once()


@pytest.mark.anyio
async def test_real_missing_lifespan_state_is_503(mock_db_session):
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    local = create_app()
    local.dependency_overrides[get_health_session_factory] = lambda: lambda: mock_db_session
    async with AsyncClient(transport=ASGITransport(app=local), base_url="http://test") as c:
        response = await c.get("/api/v1/health/ready")
    assert response.status_code == 503 and response.json()["redis"]["error"] == "REDIS_UNAVAILABLE"
