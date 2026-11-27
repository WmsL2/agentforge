"""Role probes. CLI failures never print connection credentials or exception text."""

import socket
import sys
from typing import Any

import httpx

HTTP_TIMEOUT_SECONDS = 2.0
WORKER_REPLY_TIMEOUT_SECONDS = 2.0


def http_probe(url: str) -> bool:
    try:
        response = httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False)
        return 200 <= response.status_code < 300
    except Exception:
        return False


def worker_probe(control: Any = None, hostname: str | None = None) -> bool:
    try:
        if control is None:
            from app.worker.celery_app import celery_app

            control = celery_app.control
        destination = "celery@" + (hostname or socket.gethostname())
        replies = control.ping(destination=[destination], timeout=WORKER_REPLY_TIMEOUT_SECONDS)
        return (
            isinstance(replies, list)
            and len(replies) == 1
            and replies[0] == {destination: {"ok": "pong"}}
        )
    except Exception:
        return False


def main() -> int:
    role = sys.argv[1] if len(sys.argv) == 2 else ""
    if role == "worker":
        ok = worker_probe()
    elif role == "api":
        ok = http_probe("http://127.0.0.1:8000/api/v1/health")
    elif role == "flower":
        ok = http_probe("http://127.0.0.1:5555/healthcheck")
    else:
        ok = False
    print("PROBE_OK" if ok else "PROBE_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
