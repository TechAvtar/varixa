"""Text normalisation. The original is never altered; this produces a second form.

Normalisation is conservative and fully described by ``NormalizationReport`` so
a reader can see exactly what changed (and so hidden-character counts become
an honest signal rather than being silently discarded).
"""

import re
import unicodedata
from dataclasses import dataclass, field

# Zero-width / invisible formatting characters that can hide content or break tokenisation.
_ZERO_WIDTH = {
    "​": "ZERO WIDTH SPACE",
    "‌": "ZERO WIDTH NON-JOINER",
    "‍": "ZERO WIDTH JOINER",
    "⁠": "WORD JOINER",
    "﻿": "ZERO WIDTH NO-BREAK SPACE (BOM)",
    "­": "SOFT HYPHEN",
    "᠎": "MONGOLIAN VOWEL SEPARATOR",
}
_BIDI = {"‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩"}
_SPACES = {" ", " ", " ", " ", " ", " ", " ", " ", " ", " ", " ", "　"}
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.M)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


@dataclass
class NormalizationReport:
    unicode_form: str = "NFC"
    changed: bool = False
    crlf_replaced: int = 0
    zero_width_removed: int = 0
    bidi_controls_removed: int = 0
    control_chars_removed: int = 0
    special_spaces_replaced: int = 0
    trailing_whitespace_lines: int = 0
    blank_runs_collapsed: int = 0
    zero_width_kinds: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizedText:
    original: str
    normalized: str
    report: NormalizationReport


def normalize_text(original: str) -> NormalizedText:
    report = NormalizationReport()
    text = original

    crlf = text.count("\r\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    report.crlf_replaced = crlf

    text = unicodedata.normalize("NFC", text)

    kinds: set[str] = set()
    for ch, name in _ZERO_WIDTH.items():
        n = text.count(ch)
        if n:
            report.zero_width_removed += n
            kinds.add(name)
            text = text.replace(ch, "")
    report.zero_width_kinds = sorted(kinds)

    for ch in _BIDI:
        n = text.count(ch)
        if n:
            report.bidi_controls_removed += n
            text = text.replace(ch, "")

    for ch in _SPACES:
        n = text.count(ch)
        if n:
            report.special_spaces_replaced += n
            text = text.replace(ch, " ")

    text, n = _CONTROL_RE.subn("", text)
    report.control_chars_removed = n

    text, n = _TRAILING_WS_RE.subn("", text)
    report.trailing_whitespace_lines = n

    text, n = _MULTI_BLANK_RE.subn("\n\n", text)
    report.blank_runs_collapsed = n

    text = text.strip("\n")
    report.changed = text != original
    return NormalizedText(original=original, normalized=text, report=report)
