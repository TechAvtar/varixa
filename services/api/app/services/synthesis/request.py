"""Builds the model's input from stored rows. Structured evidence only; nothing else leaves."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from app.providers.llm.base import EvidenceForModel, SynthesisRequest, TimelineForModel


def evidence_fingerprint(records: Sequence[EvidenceForModel], prompt_version: str) -> str:
    """Identifies the exact evidence set (ids, levels, claims): the cache and staleness key."""
    canon = json.dumps(
        [(e.id, e.rule, e.level, e.kind, e.claim, e.conflicts_with) for e in records],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(f"{prompt_version}\x1f{canon}".encode()).hexdigest()


def build_request(
    *,
    analysis_type: str,
    evidence_rows: Sequence[Any],
    timeline_rows: Sequence[Any],
    synthesis_confidence: float,
    prompt_version: str,
) -> SynthesisRequest:
    records: list[EvidenceForModel] = []
    counts: dict[str, int] = {}
    conflicts = 0
    for r in evidence_rows:
        d = r.details or {}
        kind = str(d.get("kind") or "signal")
        if kind == "conflict":
            conflicts += 1
        counts[r.level] = counts.get(r.level, 0) + 1
        records.append(
            EvidenceForModel(
                id=str(r.id),
                rule=str(d.get("rule") or ""),
                category=r.category,
                level=r.level,
                kind=kind,
                claim=r.claim,
                source=r.source,
                confidence=float(r.confidence) if r.confidence is not None else None,
                limitation=d.get("limitation"),
                conflicts_with=[str(x) for x in (d.get("conflicts_with") or [])],
            )
        )
    timeline = [
        TimelineForModel(
            event_type=t.event_type,
            event_time=t.event_time.isoformat() if t.event_time else None,
            certainty=t.certainty,
            description=t.description,
        )
        for t in timeline_rows
    ]
    return SynthesisRequest(
        analysis_type=analysis_type,
        evidence=records,
        timeline=timeline,
        counts=counts,
        conflicts=conflicts,
        synthesis_confidence=synthesis_confidence,
        fingerprint=evidence_fingerprint(records, prompt_version),
        prompt_version=prompt_version,
    )
