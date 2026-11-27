"""Synthetic ASGI, logging, Celery-hook and executable-probe evidence; no services."""

import asyncio
import io
import json
import logging
import os
import shutil
import subprocess
from contextlib import suppress
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
import yaml

from app.core.logging import (
    PiiRedactionFilter,
    RedactingFormatter,
    request_id_context,
    setup_logging,
)
from app.core.metrics import OperationalMetrics
from app.core.middleware import RequestIDMiddleware
from app.services import operational_probe as probe


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"x-request-id", b"a b")],
        [(b"x-request-id", b"bad\r\nvalue")],
        [(b"x-request-id", b"\xff")],
        [(b"x-request-id", b"x" * 65)],
        [(b"x-request-id", b"one"), (b"X-Request-ID", b"two")],
        [(b"x-request-id", b"a,b")],
        [(b"x-request-id", b"")],
    ],
)
async def test_invalid_ids_replaced(headers):
    messages = []

    async def app(scope, receive, send):
        assert request_id_context.get() == scope["state"]["request_id"]
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        messages.append(message)

    await RequestIDMiddleware(app)(
        {"type": "http", "headers": headers, "method": "GET", "path": "/not-logged"}, Mock(), send
    )
    value = dict(messages[0]["headers"])[b"x-request-id"].decode()
    UUID(value)
    assert request_id_context.get() is None


@pytest.mark.anyio
async def test_concurrent_ids_streaming_and_bounded_metrics(caplog):
    metrics = OperationalMetrics()
    messages = []

    async def app(scope, receive, send):
        before = request_id_context.get()
        await asyncio.sleep(0)
        assert request_id_context.get() == before == scope["state"]["request_id"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"a", "more_body": True})
        assert metrics.snapshot()["http_requests_completed_total"] < 50
        await send({"type": "http.response.body", "body": b"b"})

    async def send(message):
        messages.append(message)

    middleware = RequestIDMiddleware(app, metrics)
    caplog.set_level(logging.INFO, logger="app.core.middleware")
    await asyncio.gather(
        *(
            middleware(
                {
                    "type": "http",
                    "headers": [(b"x-request-id", f"r-{i}".encode())],
                    "method": "GET",
                    "path": f"/private-{i}",
                    "query_string": b"token=synthetic-secret",
                },
                Mock(),
                send,
            )
            for i in range(50)
        )
    )
    assert metrics.snapshot()["http_requests_completed_total"] == 50
    assert len(metrics.snapshot()["http_responses_by_status_class"]) == 5
    assert request_id_context.get() is None
    assert len([m for m in messages if m["type"] == "http.response.body"]) == 100
    completions = [r for r in caplog.records if r.msg == "http_request_completed"]
    assert len(completions) == 50 and len({r.request_id for r in completions}) == 50
    assert all("path" not in r.__dict__ for r in completions)
    assert "synthetic-secret" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["cancel", "incomplete", "partial_failure", "background_failure"])
async def test_terminal_outcomes_and_context_reset(kind):
    metrics = OperationalMetrics()

    async def app(scope, receive, send):
        if kind in ["partial_failure", "background_failure"]:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send(
                {"type": "http.response.body", "body": b"a", "more_body": kind == "partial_failure"}
            )
        if kind == "cancel":
            raise asyncio.CancelledError()
        if kind in ["partial_failure", "background_failure"]:
            raise RuntimeError("synthetic")

    async def send(message):
        pass

    middleware = RequestIDMiddleware(app, metrics)
    with suppress(asyncio.CancelledError, RuntimeError):
        await middleware(
            {"type": "http", "method": "GET", "path": "/", "headers": []}, Mock(), send
        )
    assert request_id_context.get() is None
    result = metrics.snapshot()
    assert result["http_requests_completed_total"] == (1 if kind == "background_failure" else 0)
    assert result["http_requests_cancelled_total"] == (1 if kind == "cancel" else 0)
    assert result["http_requests_incomplete_total"] == (
        1 if kind in ["incomplete", "partial_failure"] else 0
    )
    assert result["http_server_errors_total"] == 0


@pytest.mark.anyio
async def test_websocket_passes_through():
    app = Mock()

    async def inner(scope, receive, send):
        app(scope)

    scope = {"type": "websocket"}
    await RequestIDMiddleware(inner)(scope, Mock(), Mock())
    app.assert_called_once_with(scope)
    assert "state" not in scope


class ExtraFormatter(logging.Formatter):
    def format(self, record):
        return super().format(record) + " " + json.dumps(getattr(record, "payload", {}))


@pytest.mark.parametrize("name", ["", "app.synthetic.child"])
def test_effective_redaction_on_output_handlers(name):
    logger = logging.getLogger(name)
    old_handlers = logger.handlers[:]
    old_filters = logger.filters[:]
    old_level = logger.level
    old_propagate = logger.propagate
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(ExtraFormatter("%(levelname)s %(request_id)s %(message)s"))
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        setup_logging()
        formatter = handler.formatter
        setup_logging()
        assert handler.formatter is formatter
        token = request_id_context.set("correlation-safe")
        try:
            logger.warning(
                'email=%s Bearer abcdef_token sk-proj-aa_bb-ccdd123456 password="synthetic password" postgresql+asyncpg://u:db-secret@private-host/db eyJabcdefghijk.eyJabcdefghijk.signature',
                "person@example.com",
                extra={
                    "payload": {
                        "Authorization": "Bearer hidden",
                        "Cookie": "session=hidden-cookie",
                        "nested": [{"api_key": "hidden-key", "safe": 7}],
                    }
                },
            )
            try:
                raise RuntimeError("unstructured-exception-secret")
            except RuntimeError:
                logger.exception("safe operation failed")
        finally:
            request_id_context.reset(token)
        out = stream.getvalue()
        for secret in [
            "person@example.com",
            "abcdef_token",
            "aa_bb-ccdd123456",
            "synthetic password",
            "db-secret",
            "private-host",
            "eyJabcdefghijk",
            "hidden-cookie",
            "hidden-key",
            "unstructured-exception-secret",
        ]:
            assert secret not in out
        assert "correlation-safe" in out and "RuntimeError" in out and '"safe": 7' in out
    finally:
        logger.handlers = old_handlers
        logger.filters = old_filters
        logger.setLevel(old_level)
        logger.propagate = old_propagate


def test_record_not_mutated_and_no_arbitrary_repr():
    class Unsafe:
        def __str__(self):
            raise AssertionError("Must not serialize arbitrary objects")

        def __repr__(self):
            raise AssertionError("Must not serialize arbitrary objects")

    nested = {"password": "original-secret", "safe": Unsafe()}
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "value=%s", (Unsafe(),), None)
    record.payload = nested
    safe = PiiRedactionFilter().filter(record)
    assert safe is not record and record.payload["password"] == "original-secret"
    output = RedactingFormatter(ExtraFormatter()).format(record)
    assert "original-secret" not in output and "UNSUPPORTED_LOG_VALUE" in output


def test_celery_real_logging_hooks_reinstall_protection():
    from celery.signals import after_setup_logger, after_setup_task_logger

    from app.worker.celery_app import install_worker_log_redaction

    logger = logging.getLogger("celery.synthetic")
    old = logger.handlers[:]
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.handlers = [handler]
    try:
        for signal in [after_setup_logger, after_setup_task_logger]:
            handler.setFormatter(logging.Formatter("%(message)s"))
            replies = signal.send(sender=None, logger=logger)
            assert any(receiver == install_worker_log_redaction for receiver, result in replies)
            assert isinstance(handler.formatter, RedactingFormatter)
            logger.warning("api_key=worker-secret")
        assert "worker-secret" not in stream.getvalue()
    finally:
        logger.handlers = old


@pytest.mark.parametrize("status", [200, 204, 301, 401, 500, 503])
def test_http_probe_executes_status_aware_request(monkeypatch, status):
    seen = []

    def reply(request):
        seen.append(request)
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:

        def get(url, **kwargs):
            assert kwargs == {"timeout": 2.0, "follow_redirects": False}
            return client.get(url, **kwargs)

        monkeypatch.setattr(probe.httpx, "get", get)
        assert probe.http_probe("http://synthetic/health") == (200 <= status < 300)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("private-secret"), httpx.ConnectError("private-secret")]
)
def test_http_probe_errors_are_safe(monkeypatch, error, capsys):
    monkeypatch.setattr(probe.httpx, "get", Mock(side_effect=error))
    monkeypatch.setattr("sys.argv", ["probe", "flower"])
    assert probe.main() == 1 and capsys.readouterr().out == "PROBE_FAILED\n"


@pytest.mark.parametrize(
    "reply,expected",
    [
        ([{"celery@local": {"ok": "pong"}}], True),
        ([], False),
        ([{"celery@wrong": {"ok": "pong"}}], False),
        ([{"celery@local": {"ok": "not pong"}}], False),
        ({"celery@local": {"ok": "pong"}}, False),
        ([{"celery@local": "pong"}], False),
        (None, False),
    ],
)
def test_targeted_worker_reply(reply, expected):
    control = Mock()
    control.ping.return_value = reply
    assert probe.worker_probe(control, hostname="local") == expected
    control.ping.assert_called_once_with(destination=["celery@local"], timeout=2.0)


def test_worker_broker_failure():
    control = Mock()
    control.ping.side_effect = TimeoutError("redis://u:secret@private")
    assert not probe.worker_probe(control, hostname="local")


@pytest.mark.parametrize(
    "value",
    [
        "Cookie: session=first-secret; second=other-secret",
        "Authorization: Basic private-secret",
        "sk_proj_abc_def-1234567890",
        "token=private-secret",
    ],
)
def test_formatted_header_and_underscore_key_redaction(value):
    record = logging.LogRecord("app", logging.INFO, __file__, 1, value, (), None)
    out = RedactingFormatter(None).format(record)
    assert not any(
        secret in out
        for secret in ["first-secret", "other-secret", "private-secret", "abc_def-1234567890"]
    )


def test_structured_json_and_cycles_remain_bounded():
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            return json.dumps({"message": record.getMessage(), "payload": record.payload})

    record = logging.LogRecord("app", logging.INFO, __file__, 1, "safe message", (), None)
    nested = {"api_key": "not-a-real-key", "safe": 7}
    nested["cycle"] = nested
    record.payload = nested
    out = RedactingFormatter(JsonFormatter()).format(record)
    data = json.loads(out)
    assert data["payload"]["safe"] == 7 and "not-a-real-key" not in out
    assert len(out) <= 4096


@pytest.mark.parametrize("role", ["api", "worker", "flower"])
@pytest.mark.parametrize("ok", [True, False])
def test_probe_cli_exit_code(monkeypatch, capsys, role, ok):
    monkeypatch.setattr("sys.argv", ["probe", role])
    monkeypatch.setattr(probe, "http_probe", Mock(return_value=ok))
    monkeypatch.setattr(probe, "worker_probe", Mock(return_value=ok))
    assert probe.main() == (0 if ok else 1)
    assert capsys.readouterr().out == ("PROBE_OK\n" if ok else "PROBE_FAILED\n")


@pytest.mark.parametrize(
    "mode,expected", [("200", 0), ("503", 1), ("500", 1), ("timeout", 1), ("reject", 1)]
)
def test_exact_frontend_bun_probe_with_synthetic_fetch(mode, expected):
    bun = shutil.which("bun")
    if not bun:
        pytest.skip("Installed Bun unavailable; frontend probe execution NOT RUN")
    root = Path(__file__).resolve().parents[3]
    check = yaml.safe_load((root / "docker-compose.prod.yml").read_text())["services"]["frontend"][
        "healthcheck"
    ]["test"][3]
    fake = (
        "globalThis.fetch=(url,opts)=>{if(!opts.signal || opts.redirect!=='error')process.exit(9); return "
        + (
            "Promise.resolve({ok:true})"
            if mode == "200"
            else "Promise.resolve({ok:false})"
            if mode in ["500", "503"]
            else "Promise.reject(new Error('synthetic'))"
        )
        + ";};"
    )
    result = subprocess.run(
        [bun, "-e", fake + check],
        capture_output=True,
        timeout=5,
        env={
            k: os.environ[k]
            for k in ["PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"]
            if k in os.environ
        },
    )
    assert result.returncode == expected
