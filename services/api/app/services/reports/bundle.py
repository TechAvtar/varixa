"""Report bundle: everything the PDF renders, gathered from stored rows only.

The bundle is plain data (dicts, lists, bytes) so the renderer never touches the
database or storage, and so the same bundle can feed other formats later.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.services.reports.overview import OverviewDraft


@dataclass(frozen=True)
class EvidenceLine:
    rule: str
    category: str
    level: str
    kind: str
    claim: str
    source: str
    confidence: float | None
    detail: str | None
    limitation: str | None
    conflicts_with: list[str]


@dataclass(frozen=True)
class ForensicMethod:
    name: str
    applicable: bool
    observation: str | None
    confidence: str | None
    flagged: bool
    limitations: list[str]
    version: str | None
    map_png: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ReportBundle:
    analysis_id: str
    analysis_type: str
    title: str | None
    status: str
    created_at: datetime
    generated_at: datetime
    file: dict[str, Any]
    overview: OverviewDraft
    evidence: list[EvidenceLine]
    synthesis: (
        dict[str, Any] | None
    )  # {provider, model, grounded, warnings, sections: {key: {question, text, rules}}}
    metadata: dict[str, Any] | None
    provenance: dict[str, Any] | None
    ai: dict[str, Any] | None
    forensics: list[ForensicMethod]
    matches: dict[str, Any] | None  # {provider, version, searched_at, summary, items: [...]}
    timeline: list[dict[str, Any]]
    thumbnail_png: bytes | None = field(default=None, repr=False)
    app_version: str = "dev"

    def summary_json(self) -> dict[str, Any]:
        return {
            "counts": self.overview.counts,
            "synthesis_confidence": self.overview.synthesis_confidence,
            "evidence_records": len(self.evidence),
            "conflicts": len(self.overview.conflicts),
            "synthesis": bool(self.synthesis),
            "forensic_methods": [m.name for m in self.forensics if m.applicable],
            "matches": (self.matches or {}).get("summary", {}).get("match_count", 0),
            "timeline_events": len(self.timeline),
            "generated_at": self.generated_at.isoformat(),
        }


def evidence_lines(rows: Sequence[Any]) -> list[EvidenceLine]:
    out: list[EvidenceLine] = []
    for r in rows:
        d = r.details or {}
        out.append(
            EvidenceLine(
                rule=str(d.get("rule") or ""),
                category=r.category,
                level=r.level,
                kind=str(d.get("kind") or "signal"),
                claim=r.claim,
                source=r.source,
                confidence=float(r.confidence) if r.confidence is not None else None,
                detail=d.get("detail"),
                limitation=d.get("limitation"),
                conflicts_with=[str(x) for x in (d.get("conflicts_with") or [])],
            )
        )
    return out


FORENSIC_ORDER = (
    "ela",
    "compression",
    "double_compression",
    "thumbnail",
    "resampling",
    "noise",
    "copy_move",
)


def forensic_methods(row: Any | None, maps: dict[str, bytes]) -> list[ForensicMethod]:
    if row is None:
        return []
    out: list[ForensicMethod] = []
    for name in FORENSIC_ORDER:
        j = getattr(row, f"{name}_json", None)
        if not isinstance(j, dict):
            continue
        applicable = bool(j.get("applicable"))
        flagged = bool(
            j.get("anomaly") or j.get("detected") or j.get("prior_jpeg_grid") or j.get("flagged")
        )
        out.append(
            ForensicMethod(
                name=name,
                applicable=applicable,
                observation=j.get("observation") if applicable else j.get("reason"),
                confidence=j.get("confidence") if applicable else None,
                flagged=flagged and applicable,
                limitations=[str(x) for x in (j.get("limitations") or [])],
                version=j.get("version"),
                map_png=maps.get(name),
            )
        )
    return out
