"""Timeline builder: dated evidence becomes ordered events, each labelled with its certainty.

Sources of time (docs/05 §8): C2PA signing time and action times, metadata capture and
modification times, source publication and discovery times, plus the analysis' own
submission time. Nothing is inferred: an event exists only where a subsystem recorded
a time, its certainty is the level of the evidence record it comes from, and events
whose time could not be parsed keep the raw string and sort last.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.enums import EvidenceLevel
from app.services.evidence.engine import EvidenceDraft, Observations
from app.utils.timeparse import as_utc, parse_timestamp

TIMELINE_VERSION = "v1"

LIMITATIONS = [
    "Every event is a time some system *recorded*, not an observed fact about the world. "
    "Camera clocks drift, EXIF fields can be edited, and provider dates are as reported.",
    "Times without a timezone are shown as recorded and, when placed on the line, treated as "
    "UTC; their position can be off by the local offset.",
    "Absence of events (no capture time, no credentials, no sources) says nothing about the "
    "content's history.",
]


@dataclass(frozen=True)
class TimelineEventDraft:
    event_type: str
    certainty: str
    description: str
    source: str
    event_time: datetime | None  # tz-aware UTC when placeable on the line
    raw_time: str | None
    tz_known: bool
    source_rules: list[str] = field(default_factory=list)  # evidence rule ids this came from
    data: dict[str, Any] = field(default_factory=dict)


def _placeable(dt: datetime | None) -> datetime | None:
    return as_utc(dt) if dt is not None else None


def build_timeline(o: Observations, drafts: Sequence[EvidenceDraft]) -> list[TimelineEventDraft]:
    """Events in chronological order (undated last), derived only from recorded times."""
    by_rule = {d.rule: d for d in drafts}
    events: list[TimelineEventDraft] = []

    # -- provenance: signing time and dated actions ------------------------------------------
    prov = by_rule.get("provenance.valid") or by_rule.get("provenance.invalid")
    if prov is not None and o.provenance is not None:
        certainty = prov.level  # VERIFIED for an intact manifest, POSSIBLE otherwise
        signed_raw = o.provenance.signed_at
        dt, tz = parse_timestamp(signed_raw)
        if signed_raw:
            events.append(
                TimelineEventDraft(
                    event_type="provenance.signed",
                    certainty=certainty,
                    description="C2PA manifest signed"
                    + (f" by {o.provenance.signer}" if o.provenance.signer else "")
                    + (
                        "."
                        if certainty == EvidenceLevel.VERIFIED
                        else " (validation reported problems)."
                    ),
                    source=prov.source,
                    event_time=_placeable(dt),
                    raw_time=str(signed_raw),
                    tz_known=tz,
                    source_rules=[prov.rule],
                )
            )
        for action in (o.provenance.normalized_json or {}).get("actions") or []:
            when = action.get("when") if isinstance(action, dict) else None
            if not when:
                continue
            dt, tz = parse_timestamp(when)
            name = str(action.get("action") or "action")
            agent = action.get("software_agent")
            events.append(
                TimelineEventDraft(
                    event_type=f"provenance.action:{name}",
                    certainty=certainty,
                    description=f"Manifest records the action {name}"
                    + (f" by {agent}" if agent else "")
                    + ".",
                    source=prov.source,
                    event_time=_placeable(dt),
                    raw_time=str(when),
                    tz_known=tz,
                    source_rules=[prov.rule],
                    data={"action": name, "software_agent": agent},
                )
            )

        for entry in (o.provenance.normalized_json or {}).get("manifest_chain") or []:
            if not isinstance(entry, dict) or not entry.get("parent") or not entry.get("signed_at"):
                continue  # the active manifest is the "provenance.signed" event above
            dt, tz = parse_timestamp(entry["signed_at"])
            events.append(
                TimelineEventDraft(
                    event_type="provenance.ingredient-signed",
                    certainty=certainty,
                    description="An ingredient's manifest was signed"
                    + (f" by {entry.get('signer')}" if entry.get("signer") else "")
                    + ".",
                    source=prov.source,
                    event_time=_placeable(dt),
                    raw_time=str(entry["signed_at"]),
                    tz_known=tz,
                    source_rules=[prov.rule],
                    data={
                        "manifest": entry.get("label"),
                        "claim_generator": entry.get("claim_generator"),
                    },
                )
            )

    # -- metadata: capture and modification times --------------------------------------------
    meta = o.metadata
    if meta is not None:
        n = meta.normalized_json or {}
        src = f"metadata/{meta.engine}"
        for key, label, rule in (
            ("captured_at", "Capture time recorded in metadata", "metadata.captured"),
            ("modified_at", "Modification time recorded in metadata", "metadata.modified"),
            ("gps_time", "GPS receiver time recorded in metadata (UTC)", "metadata.gps"),
        ):
            ts = n.get(key)
            if not ts or not ts.get("raw"):
                continue
            dt, tz = parse_timestamp(ts.get("parsed") or ts.get("raw"))
            linked = by_rule.get(rule)
            events.append(
                TimelineEventDraft(
                    event_type=f"metadata.{key.removesuffix('_at').removesuffix('_time')}"
                    + ("_time" if key == "gps_time" else ""),
                    certainty=linked.level if linked else EvidenceLevel.POSSIBLE,
                    description=label + ("" if tz else " (timezone not recorded)") + ".",
                    source=src,
                    event_time=_placeable(dt),
                    raw_time=str(ts.get("raw")),
                    tz_known=bool(tz),
                    source_rules=[linked.rule] if linked else [],
                )
            )

    # -- metadata: XMP edit history (each action has its own recorded time) -------------------
    if meta is not None:
        n = meta.normalized_json or {}
        linked = by_rule.get("metadata.edit-history")
        for item in (n.get("edit_history") or [])[:50]:
            when = item.get("when")
            action = str(item.get("action") or "edit")
            dt, tz = parse_timestamp(str(when)) if when else (None, False)
            agent = item.get("software")
            events.append(
                TimelineEventDraft(
                    event_type="metadata.edit",
                    certainty=linked.level if linked else EvidenceLevel.POSSIBLE,
                    description=f"Edit history: {action}"
                    + (f" by {agent}" if agent else "")
                    + ("" if tz else " (timezone not recorded)")
                    + ".",
                    source=f"metadata/{meta.engine}",
                    event_time=_placeable(dt),
                    raw_time=str(when) if when else None,
                    tz_known=bool(tz),
                    source_rules=[linked.rule] if linked else [],
                )
            )

    # -- sources: reported publication and our discovery -------------------------------------
    sources = by_rule.get("sources.matches")
    if sources is not None:
        for m in o.search_matches:
            published = getattr(m, "published_at", None)
            if published:
                dt, tz = parse_timestamp(published)
                events.append(
                    TimelineEventDraft(
                        event_type="source.published",
                        certainty=EvidenceLevel.POSSIBLE,
                        description="A matching source reports a publication date"
                        + (f" ({m.url})" if getattr(m, "url", None) else "")
                        + ".",
                        source=sources.source,
                        event_time=_placeable(dt),
                        raw_time=str(published),
                        tz_known=tz,
                        source_rules=[sources.rule],
                        data={"url": getattr(m, "url", None)},
                    )
                )
            discovered = getattr(m, "discovered_at", None)
            if discovered:
                dt, tz = parse_timestamp(discovered)
                events.append(
                    TimelineEventDraft(
                        event_type="source.discovered",
                        certainty=EvidenceLevel.VERIFIED,
                        description="The source search returned this match"
                        + (f" ({m.url})" if getattr(m, "url", None) else "")
                        + ".",
                        source=sources.source,
                        event_time=_placeable(dt),
                        raw_time=dt.isoformat() if dt else str(discovered),
                        tz_known=True,
                        source_rules=[sources.rule],
                        data={"url": getattr(m, "url", None)},
                    )
                )

    # -- this analysis --------------------------------------------------------------------------
    if o.file is not None and o.submitted_at is not None:
        events.append(
            TimelineEventDraft(
                event_type="analysis.submitted",
                certainty=EvidenceLevel.VERIFIED,
                description="Submitted to Verixa for analysis.",
                source="verixa",
                event_time=_placeable(o.submitted_at),
                raw_time=as_utc(o.submitted_at).isoformat(),
                tz_known=True,
                source_rules=["file.identity"] if "file.identity" in by_rule else [],
            )
        )

    dated = sorted((e for e in events if e.event_time is not None), key=lambda e: e.event_time)  # type: ignore[arg-type, return-value]
    undated = [e for e in events if e.event_time is None]
    return [*dated, *undated]
