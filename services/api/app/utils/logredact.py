"""Log redaction: secrets never reach a log line, whichever logger wrote it (docs/09).

Installed once per process as the ``logging`` record factory, so it also covers third-party
loggers such as uvicorn's access log (which would otherwise print signed download URLs).
Redaction runs on the message template and on string arguments before formatting.
"""

import logging
import re
from typing import Any

REDACTED = "[redacted]"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization header values and bearer tokens anywhere in the text.
    (re.compile(r"(?i)\b(bearer\s+)[a-z0-9._~+/=-]+"), r"\1" + REDACTED),
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*)[^\s,;]+"), r"\1" + REDACTED),
    # Query-string / key=value secrets: signed-URL signatures, tokens, keys, passwords.
    (
        re.compile(
            r"(?i)\b((?:sig|signature|token|access_token|refresh_token|api_key|apikey|"
            r"password|secret|secret_key)=)[^&\s\"'#]+"
        ),
        r"\1" + REDACTED,
    ),
    # JWT-shaped strings and OpenAI-style API keys.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), REDACTED),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_value(value: Any) -> Any:
    return redact(value) if isinstance(value, str) else value


def install_log_redaction() -> None:
    """Wrap the current LogRecord factory so every record is scrubbed. Idempotent."""
    current = logging.getLogRecordFactory()
    if getattr(current, "verixa_redacting", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_value(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _redact_value(v) for k, v in record.args.items()}
        return record

    factory.verixa_redacting = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
