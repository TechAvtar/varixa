"""Structured logging with request and analysis correlation (docs/09 "safe logging").

Every record carries ``request_id`` and ``analysis_id`` when they are known, taken from
context variables set by the request middleware and the pipeline runner. Two formats:
``json`` (one object per line, for log shippers) and ``text`` (key=value, for terminals).
What is logged is always identifiers, statuses, durations and provider names; never
content, tokens or keys (``logredact`` scrubs the latter as a second line of defence).
"""

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Literal

LogFormat = Literal["text", "json"]

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "verixa_request_id", default=""
)
analysis_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "verixa_analysis_id", default=""
)

# LogRecord attributes that are not user-supplied ``extra`` fields.
_STANDARD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
        "request_id",
        "analysis_id",
    }
)


class ContextFilter(logging.Filter):
    """Attach the current correlation ids to every record (empty when unknown)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", ""):
            record.request_id = request_id_var.get()
        if not getattr(record, "analysis_id", ""):
            record.analysis_id = analysis_id_var.get()
        return True


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "analysis_id"):
            value = getattr(record, key, "")
            if value:
                payload[key] = value
        payload.update(_extras(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        parts = [
            datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S.%f")[:-3],
            record.levelname,
            record.name,
            record.getMessage(),
        ]
        for key in ("request_id", "analysis_id"):
            value = getattr(record, key, "")
            if value:
                parts.append(f"{key}={value}")
        parts.extend(f"{k}={v}" for k, v in _extras(record).items())
        line = " ".join(str(p) for p in parts)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def build_handler(fmt: LogFormat) -> logging.Handler:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else KeyValueFormatter())
    handler.addFilter(ContextFilter())
    handler.set_name("verixa")
    return handler


def configure_logging(*, level: str, fmt: LogFormat) -> None:
    """Install one structured handler on the root logger. Safe to call repeatedly."""
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == "verixa":
            root.removeHandler(existing)
    root.addHandler(build_handler(fmt))
    root.setLevel(level.upper())
    # Tooling that runs in-process before the app (alembic's fileConfig, for one) may have
    # disabled loggers that already existed; our loggers must always be live.
    for name, logger in logging.root.manager.loggerDict.items():
        if name.startswith("verixa") and isinstance(logger, logging.Logger):
            logger.disabled = False
    # Our request log replaces uvicorn's access line (which would also print query strings).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
