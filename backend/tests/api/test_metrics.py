"""Machine-authenticated, process-local metrics and real HTTP observation contracts."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.main import create_app


@pytest.mark.anyio
async def test_metrics_auth_and_no_self_observation():
    app = create_app()

    @app.get("/failure")
    async def failure():
        raise RuntimeError("postgresql://user:synthetic-secret@private-host/db")

    @app.get("/handled")
    async def handled():
        raise AuthenticationError(message="Denied")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/metrics")).status_code == 401
        assert (
            await client.get("/api/v1/metrics", headers={settings.API_KEY_HEADER: "wrong"})
        ).status_code == 403
        assert (
            await client.get("/api/v1/metrics", headers={settings.API_KEY_HEADER.encode(): b"\xff"})
        ).status_code == 403
        headers = {settings.API_KEY_HEADER: settings.API_KEY}
        before = (await client.get("/api/v1/metrics", headers=headers)).json()
        assert before["http_requests_completed_total"] == 0
        ok = await client.get("/api/v1/health", headers={"X-Request-ID": "safe-id"})
        handled = await client.get("/handled")
        failed = await client.get("/failure", headers={"X-Request-ID": "failure-id"})
        assert handled.status_code == 401 and handled.headers["www-authenticate"] == "Bearer"
        assert failed.status_code == 500 and failed.headers["x-request-id"] == "failure-id"
        assert "synthetic-secret" not in failed.text
        assert ok.headers["x-request-id"] == "safe-id"
        snapshot = (await client.get("/api/v1/metrics", headers=headers)).json()
        assert snapshot["http_requests_completed_total"] == 3
        assert snapshot["http_responses_by_status_class"] == {
            "1xx": 0,
            "2xx": 1,
            "3xx": 0,
            "4xx": 1,
            "5xx": 1,
        }
        assert snapshot["http_server_errors_total"] == 1
        assert snapshot["http_request_duration_seconds"]["count"] == 3
        assert snapshot["http_request_duration_seconds"]["sum"] >= 0
        assert (
            snapshot["scope"] == "api_process_application_instance" and not snapshot["persistent"]
        )
        assert (await client.get("/api/v1/metrics", headers=headers)).json() == snapshot
        assert settings.API_KEY not in str(snapshot)
    assert create_app().state.operational_metrics.snapshot()["http_requests_completed_total"] == 0


@pytest.mark.anyio
async def test_non_ascii_api_key_is_denied_without_type_error():
    from app.api.deps import verify_api_key
    from app.core.exceptions import AuthorizationError

    with pytest.raises(AuthorizationError):
        await verify_api_key("clé")
