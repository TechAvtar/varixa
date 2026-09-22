"""Filename hygiene for untrusted upload names. Pure; no I/O."""

import re
import unicodedata

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SEPARATORS = re.compile(r"[\\/]+")
_QUOTES = re.compile(r"[\"']")
MAX_FILENAME = 255


def safe_filename(name: str | None, *, max_length: int = MAX_FILENAME) -> str | None:
    """A display/download name with no path, control characters, quotes or leading dots.

    Returns None when nothing usable remains; callers choose their own fallback.
    Only used for titles and Content-Disposition; object keys never derive from it.
    """
    if not name:
        return None
    text = unicodedata.normalize("NFKC", name)
    text = _CONTROL.sub("", text)
    text = _SEPARATORS.split(text)[-1]  # basename only, for both separator styles
    text = _QUOTES.sub("", text).strip().lstrip(".").strip()
    return text[:max_length] or None
