"""Application middleware."""

import asyncio
import logging
import re
from time import perf_counter
from typing import ClassVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_context
from app.core.metrics import OperationalMetrics


class RequestIDMiddleware:
    """Outer HTTP observer; no buffering, WebSocket changes or untrusted URL logs."""

    def __init__(
        self,
        app: ASGIApp,
        metrics: OperationalMetrics | None = None,
        metrics_path: str = "/api/v1/metrics",
    ) -> None:
        self.app, self.metrics, self.metrics_path = app, metrics, metrics_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        values = [v for k, v in scope.get("headers", []) if k.lower() == b"x-request-id"]
        value = values[0] if len(values) == 1 else b""
        request_id = (
            value.decode("ascii")
            if re.fullmatch(rb"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value)
            else str(uuid4())
        )
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        start, status, finished, cancelled = perf_counter(), None, None, False

        async def observed_send(message: Message) -> None:
            nonlocal status, finished
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"
                ] + [(b"x-request-id", request_id.encode("ascii"))]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = perf_counter()

        try:
            await self.app(scope, receive, observed_send)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            try:
                duration = (finished if finished is not None else perf_counter()) - start
                if (
                    self.metrics is not None
                    and scope.get("path", "").rstrip("/") != self.metrics_path
                ):
                    self.metrics.observe(
                        status, duration, completed=finished is not None, cancelled=cancelled
                    )
                method = scope.get("method", "")
                logging.getLogger(__name__).info(
                    "http_request_completed",
                    extra={
                        "request_id": request_id,
                        "method": method
                        if method
                        in {
                            "GET",
                            "POST",
                            "PUT",
                            "PATCH",
                            "DELETE",
                            "HEAD",
                            "OPTIONS",
                            "TRACE",
                            "CONNECT",
                        }
                        else "OTHER",
                        "status_code": status,
                        "duration_ms": round(max(0.0, duration) * 1000, 3),
                        "outcome": "completed"
                        if finished is not None
                        else "cancelled"
                        if cancelled
                        else "incomplete",
                    },
                )
            finally:
                request_id_context.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses.

    This includes:
    - Content-Security-Policy (CSP)
    - X-Content-Type-Options
    - X-Frame-Options
    - X-XSS-Protection
    - Referrer-Policy
    - Permissions-Policy

    Usage:
        app.add_middleware(SecurityHeadersMiddleware)

        # Or with custom CSP:
        app.add_middleware(
            SecurityHeadersMiddleware,
            csp_directives={
                "default-src": "'self'",
                "script-src": "'self' 'unsafe-inline'",
            }
        )
    """

    DEFAULT_CSP_DIRECTIVES: ClassVar[dict[str, str]] = {
        "default-src": "'self'",
        "script-src": "'self'",
        "style-src": "'self' 'unsafe-inline'",  # Allow inline styles for some UI libs
        "img-src": "'self' data: https:",
        "font-src": "'self' data:",
        "connect-src": "'self'",
        "frame-ancestors": "'none'",
        "base-uri": "'self'",
        "form-action": "'self'",
    }

    def __init__(
        self,
        app: ASGIApp,
        csp_directives: dict[str, str] | None = None,
        exclude_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.csp_directives = csp_directives or self.DEFAULT_CSP_DIRECTIVES
        self.exclude_paths = exclude_paths or {"/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add security headers to the response."""
        response = await call_next(request)

        if request.url.path in self.exclude_paths:
            return response

        csp_value = "; ".join(
            f"{directive} {value}" for directive, value in self.csp_directives.items()
        )

        # Respect any already-set headers so an endpoint can opt into less
        # restrictive framing (e.g. user-content files in the chat preview panel).
        response.headers.setdefault("Content-Security-Policy", csp_value)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        return response
