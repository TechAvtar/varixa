"""Overview assembly: the report's first page, built only from stored records.

Groups evidence by what a reader must know first (docs/07 summary template, docs/08
report): verified facts, strong evidence, probabilistic signals, conflicts, unknowns,
plus the methodology notes that make the report auditable (what ran, with which
engines and versions, under which thresholds, and what the levels mean). The PDF
export (T036) renders the same structure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.enums import EvidenceLevel
from app.services.evidence.engine import EvidenceThresholds, synthesis_confidence

OVERVIEW_VERSION = "v1"

LEVEL_DEFINITIONS: dict[str, str] = {
    EvidenceLevel.VERIFIED: "Directly established by cryptographic or deterministic evidence "
    "(hashes, intact signatures, decoded file properties).",
    EvidenceLevel.STRONG: "A technical observation with meaningful evidentiary value "
    "(explicit editing-software metadata, several independent forensic anomalies).",
    EvidenceLevel.PROBABLE: "Evidence supports an interpretation but uncertainty remains "
    "(a calibrated detector's high score, a confident language guess).",
    EvidenceLevel.POSSIBLE: "A signal worth considering but insufficient alone "
    "(a single heuristic, a reverse-search hit, recorded metadata values).",
    EvidenceLevel.UNKNOWN: "The system cannot establish the fact. Absence of evidence is "
    "never treated as evidence.",
}

METHODOLOGY_NOTES = [
    "Deterministic checks run before any interpretation: the stored bytes are hashed and "
    "decoded, metadata and content credentials are read as recorded, and forensic "
    "heuristics are measured, each with its own limitations.",
    "Levels are assigned only by the evidence engine's rules; no model, provider or person "
    "raises a level. Correlated signals share a family so they are not counted twice.",
    "A detector score is a probabilistic signal, never proof of authorship. Missing metadata "
    "or credentials is UNKNOWN, not evidence of editing. A reverse-search hit shows where "
    "similar content was found, not where it came from.",
    "Contradictory evidence is kept on both sides and surfaced as a conflict, which lowers "
    "the synthesis confidence.",
    "Every external call is audited with provider, operation, version, latency and status; "
    "raw uploaded content is never logged and only structured evidence reaches a language "
    "model.",
]


@dataclass(frozen=True)
class EngineNote:
    provider: str
    model_version: str | None
    operations: list[str]
    calls: int
    cached: int
    failed: int


@dataclass(frozen=True)
class StepNote:
    name: str
    status: str
    duration_ms: int | None
    error_code: str | None


@dataclass(frozen=True)
class OverviewDraft:
    verified: list[Any]
    strong: list[Any]
    probabilistic: list[Any]
    conflicts: list[Any]
    unknown: list[Any]
    counts: dict[str, int]
    synthesis_confidence: float
    steps: list[StepNote]
    engines: list[EngineNote]
    thresholds: dict[str, Any]
    level_definitions: dict[str, str] = field(default_factory=lambda: dict(LEVEL_DEFINITIONS))
    methodology: list[str] = field(default_factory=lambda: list(METHODOLOGY_NOTES))


def _kind(row: Any) -> str:
    return str((row.details or {}).get("kind") or "signal")


def build_overview(
    *,
    evidence_rows: Sequence[Any],
    steps: Sequence[Any],
    provider_calls: Sequence[Any],
    thresholds: EvidenceThresholds,
) -> OverviewDraft:
    """Deterministic grouping of stored rows; nothing is computed that is not already recorded."""
    verified: list[Any] = []
    strong: list[Any] = []
    probabilistic: list[Any] = []
    conflicts: list[Any] = []
    unknown: list[Any] = []
    counts = {level.value: 0 for level in EvidenceLevel}
    for r in evidence_rows:
        counts[r.level] = counts.get(r.level, 0) + 1
        kind = _kind(r)
        if kind == "conflict":
            conflicts.append(r)
        elif r.level == EvidenceLevel.VERIFIED:
            verified.append(r)
        elif r.level == EvidenceLevel.STRONG:
            strong.append(r)
        elif r.level in {EvidenceLevel.PROBABLE, EvidenceLevel.POSSIBLE}:
            probabilistic.append(r)
        else:
            unknown.append(r)

    confidence = synthesis_confidence(
        [
            (r.level, float(r.confidence) if r.confidence is not None else None, _kind(r))
            for r in evidence_rows
        ],
        thresholds,
    )

    engines: dict[tuple[str, str | None], dict[str, Any]] = {}
    for c in provider_calls:
        key = (str(c.provider), c.model_version)
        e = engines.setdefault(key, {"operations": [], "calls": 0, "cached": 0, "failed": 0})
        e["calls"] += 1
        if str(c.status) == "cached":
            e["cached"] += 1
        if str(c.status) in {"failed", "timeout"}:
            e["failed"] += 1
        if c.operation not in e["operations"]:
            e["operations"].append(str(c.operation))

    return OverviewDraft(
        verified=verified,
        strong=strong,
        probabilistic=probabilistic,
        conflicts=conflicts,
        unknown=unknown,
        counts=counts,
        synthesis_confidence=confidence,
        steps=[
            StepNote(
                name=str(s.name),
                status=str(s.status),
                duration_ms=s.duration_ms,
                error_code=s.error_code,
            )
            for s in steps
        ],
        engines=[
            EngineNote(
                provider=p,
                model_version=v,
                operations=sorted(e["operations"]),
                calls=e["calls"],
                cached=e["cached"],
                failed=e["failed"],
            )
            for (p, v), e in sorted(engines.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
        ],
        thresholds=thresholds.to_json(),
    )
