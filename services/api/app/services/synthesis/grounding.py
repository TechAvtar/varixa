"""Grounding checks: the model's prose is accepted only where it points at real evidence.

The model cannot create evidence or change levels (docs/07), and we do not take its word
for it. Every section is checked against the evidence set that was sent:

* citations that do not name a sent record are dropped and counted;
* a section with substantive text but no valid citation is *ungrounded* (``improve`` is
  exempt: it is advice about missing evidence, not a claim about the content);
* level words the evidence does not contain, and certainty phrasing that no VERIFIED
  record supports, are recorded as warnings.

The result carries ``grounded`` (all substantive sections cite valid evidence and no
level was invented) and a list of warnings that the report shows next to the prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.providers.llm.base import SECTION_KEYS, SectionDraft

LEVELS = ("VERIFIED", "STRONG", "PROBABLE", "POSSIBLE", "UNKNOWN")
# Phrases that assert certainty. Allowed only when a VERIFIED record exists.
CERTAINTY_PATTERNS = (
    r"\bproves?\b",
    r"\bproof that\b",
    r"\bdefinitively\b",
    r"\bcertainly\b",
    r"\bconfirmed to be\b",
    r"\bis (?:ai[- ]generated|manipulated|edited|fake|authentic|the original)\b",
    r"\bwas (?:ai[- ]generated|manipulated|edited|faked)\b",
)
_CERTAINTY = re.compile("|".join(CERTAINTY_PATTERNS), re.IGNORECASE)
_LEVEL_WORD = re.compile(r"\b(VERIFIED|STRONG|PROBABLE|POSSIBLE|UNKNOWN)\b")
# Up to this many characters a section is treated as a single "nothing to report" sentence
# that needs no citation; longer text makes statements and must cite evidence.
MIN_SUBSTANTIVE_CHARS = 120
EXEMPT_SECTIONS = frozenset({"improve"})


@dataclass(frozen=True)
class GroundedSection:
    text: str
    evidence_ids: list[str]
    dropped_ids: list[str]
    grounded: bool


@dataclass(frozen=True)
class GroundingReport:
    sections: dict[str, GroundedSection]
    grounded: bool
    warnings: list[str] = field(default_factory=list)
    cited_ids: list[str] = field(default_factory=list)


def check_grounding(
    sections: dict[str, SectionDraft],
    *,
    evidence_ids: set[str],
    levels_present: set[str],
) -> GroundingReport:
    out: dict[str, GroundedSection] = {}
    warnings: list[str] = []
    cited: list[str] = []
    all_grounded = True
    has_verified = "VERIFIED" in levels_present

    for key in SECTION_KEYS:
        draft = sections.get(key) or SectionDraft(text="")
        valid = [i for i in draft.evidence_ids if i in evidence_ids]
        dropped = [i for i in draft.evidence_ids if i not in evidence_ids]
        if dropped:
            warnings.append(
                f"'{key}' cited {len(dropped)} id(s) that are not in the evidence; dropped."
            )
        substantive = len(draft.text.strip()) >= MIN_SUBSTANTIVE_CHARS
        grounded = bool(valid) or not substantive or key in EXEMPT_SECTIONS
        if not grounded:
            warnings.append(f"'{key}' makes statements without citing any evidence record.")
            all_grounded = False
        for level in set(_LEVEL_WORD.findall(draft.text)):
            if level not in levels_present:
                warnings.append(
                    f"'{key}' mentions the level {level}, which no evidence record carries."
                )
                all_grounded = False
        if not has_verified and _CERTAINTY.search(draft.text):
            warnings.append(
                f"'{key}' uses certainty wording although nothing is VERIFIED; treat with care."
            )
        cited.extend(i for i in valid if i not in cited)
        out[key] = GroundedSection(
            text=draft.text.strip(), evidence_ids=valid, dropped_ids=dropped, grounded=grounded
        )
    return GroundingReport(sections=out, grounded=all_grounded, warnings=warnings, cited_ids=cited)
