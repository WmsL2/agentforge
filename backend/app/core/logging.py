"""Bounded application-output redaction, not a universal secret/compliance guarantee."""

import logging
import re
from contextvars import ContextVar
from itertools import islice
from typing import Any, ClassVar

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
MAX_TEXT = 4096
OVERSIZED_TEXT = "[OVERSIZED_LOG_TEXT_REDACTED]"
SENSITIVE_KEY = re.compile(
    r"password|passwd|pwd|secret|token|api[-_]?key|authorization|cookie|connection[-_]?url|dsn",
    re.IGNORECASE,
)


class PiiRedactionFilter(logging.Filter):
    """Return a sanitized copy (Python 3.12+); never mutate a shared input record."""

    PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        (re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/]+:[^\s]*"), "[CONNECTION_URL_REDACTED]"),
        (re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}"), "[EMAIL_REDACTED]"),
        (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "[JWT_REDACTED]"),
        (re.compile(r"\bsk[-_][A-Za-z0-9_-]{8,}"), "[API_KEY_REDACTED]"),
        (
            # Unstructured headers have no reliable end delimiter (cookies contain
            # semicolons and may have continuations). Discard the full suffix.
            re.compile(r"(\b(?:authorization|(?:set-)?cookie)[ \t]*[:=][ \t]*).*", re.I | re.S),
            r"\1[REDACTED]",
        ),
        (re.compile(r"Bearer\s+[^\s,;\"']+", re.IGNORECASE), "Bearer [TOKEN_REDACTED]"),
        (
            re.compile(
                r"(\b(?:password|passwd|pwd|secret(?:_key)?|api[-_]?key|token|auth_token|access_token|refresh_token|authorization|(?:set-)?cookie)[\"']?\s*[=:]\s*)"
                r"""(?:"(?:[^"\\]|\\[\s\S])*(?:"|\\?\Z)|'(?:[^'\\]|\\[\s\S])*(?:'|\\?\Z)|[^\s,;}"']+)""",
                re.IGNORECASE,
            ),
            r'\1"[REDACTED]"',
        ),
    ]

    def _redact(self, value: str) -> str:
        if len(value) > MAX_TEXT:
            return OVERSIZED_TEXT
        for pattern, replacement in self.PATTERNS:
            value = pattern.sub(replacement, value)
            if len(value) > MAX_TEXT:
                return OVERSIZED_TEXT
        return value

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:  # ty: ignore[invalid-method-override]
        # Project requires Python >=3.12; legacy ty target is 3.11 (bool-only filter stub).
        safe = logging.makeLogRecord({})
        budget = [128]

        def scrub(value: Any, depth: int = 0) -> Any:
            budget[0] -= 1
            if budget[0] < 0 or depth > 5:
                return "[TRUNCATED]"
            if isinstance(value, str):
                return self._redact(value)
            if value is None or type(value) in (int, float, bool):
                return value
            if type(value) is dict:
                result = {}
                for i, (k, v) in enumerate(value.items()):
                    if i >= 32:
                        break
                    key = self._redact(k) if isinstance(k, str) else "[KEY]"
                    result[key] = (
                        "[REDACTED]"
                        if isinstance(k, str) and SENSITIVE_KEY.search(k)
                        else scrub(v, depth + 1)
                    )
                return result
            if type(value) in (list, tuple):
                entries = [scrub(v, depth + 1) for v in value[:32]]
                return tuple(entries) if type(value) is tuple else entries
            return "[UNSUPPORTED_LOG_VALUE]"

        for key, value in islice(record.__dict__.items(), 128):
            if key in {"exc_info", "exc_text", "stack_info"}:
                continue
            safe.__dict__[key] = "[REDACTED]" if SENSITIVE_KEY.search(key) else scrub(value)
        safe.exc_info = None
        exception_type = (
            type(record.exc_info[1]).__name__[:80]
            if record.exc_info
            else getattr(record, "_safe_exception_type", None)
        )
        safe_type = (
            exception_type
            if isinstance(exception_type, str)
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", exception_type)
            else None
        )
        safe.__dict__["_safe_exception_type"] = safe_type
        safe.exc_text = (
            f"{safe_type}: [exception details redacted]"
            if safe_type
            else "[exception details redacted]"
            if record.exc_text
            else None
        )
        safe.stack_info = "[stack details redacted]" if record.stack_info else None
        safe.request_id = request_id_context.get() or getattr(safe, "request_id", None) or "-"
        return safe


class RedactingFormatter(logging.Formatter):
    """Preserve delegate formatting/levels while protecting its input and output."""

    def __init__(self, delegate: logging.Formatter | None) -> None:
        super().__init__()
        self.delegate = delegate or logging.Formatter()
        self.redactor = PiiRedactionFilter()

    def format(self, record: logging.LogRecord) -> str:
        safe = self.redactor.filter(record)
        try:
            rendered = self.delegate.format(safe)
        except Exception:
            return "LOG_FORMAT_FAILED [details redacted]"
        return self.redactor._redact(rendered)


def setup_logging(logger: logging.Logger | None = None) -> None:
    """Idempotently protect current output handlers; rerun after Celery setup."""
    root = logging.getLogger()
    if not any(isinstance(f, PiiRedactionFilter) for f in root.filters):
        root.addFilter(PiiRedactionFilter())  # ty: ignore[invalid-argument-type]
    loggers = [
        root,
        *[v for v in root.manager.loggerDict.values() if isinstance(v, logging.Logger)],
    ]
    if logger is not None:
        loggers.append(logger)
    handlers = {h for item in loggers for h in item.handlers}
    if logging.lastResort is not None:
        handlers.add(logging.lastResort)
    for handler in handlers:
        if not isinstance(handler.formatter, RedactingFormatter):
            handler.setFormatter(RedactingFormatter(handler.formatter))


def setup_api_logging() -> None:
    """Supply app output for Uvicorn's default, which configures only its own loggers."""
    app_logger = logging.getLogger("app")
    root = logging.getLogger()
    if (
        not app_logger.disabled
        and app_logger.level == logging.NOTSET
        and app_logger.propagate
        and not app_logger.hasHandlers()
        and root.level == logging.WARNING
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(levelname)s %(name)s request_id=%(request_id)s %(message)s "
                "exception_type=%(exception_type)s",
                defaults={"exception_type": "-"},
            )
        )
        app_logger.addHandler(handler)
        app_logger.setLevel(logging.INFO)
        app_logger.propagate = False
    setup_logging()
