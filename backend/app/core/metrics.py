"""Bounded process/application-local HTTP counters; no persistence or labels."""

from threading import Lock
from typing import Any


class OperationalMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._classes = dict.fromkeys(("1xx", "2xx", "3xx", "4xx", "5xx"), 0)
        self._count = 0
        self._seconds = 0.0
        self._cancelled = 0
        self._incomplete = 0

    def observe(
        self, status: int | None, seconds: float, *, completed: bool, cancelled: bool
    ) -> None:
        with self._lock:
            if completed and status is not None and 100 <= status < 600:
                self._count += 1
                self._classes[f"{status // 100}xx"] += 1
                self._seconds += max(0.0, seconds)
            elif cancelled:
                self._cancelled += 1
            else:
                self._incomplete += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "scope": "api_process_application_instance",
                "persistent": False,
                "http_requests_completed_total": self._count,
                "http_responses_by_status_class": dict(self._classes),
                "http_request_duration_seconds": {"count": self._count, "sum": self._seconds},
                "http_server_errors_total": self._classes["5xx"],
                "http_requests_cancelled_total": self._cancelled,
                "http_requests_incomplete_total": self._incomplete,
            }
