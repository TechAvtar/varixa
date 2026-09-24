"""Evidence engine: turns every subsystem's persisted observation into leveled evidence records.

Pure and deterministic: it reads ORM rows (or anything with the same attributes) and
returns ``EvidenceDraft`` objects; the pipeline step persists them. Rules follow
docs/07-EVIDENCE-ENGINE.md:

* levels come only from the initial rules table, never from an LLM;
* thresholds live in ``EvidenceThresholds`` (built from ``Settings``), not in the rules;
* correlated signals are grouped into *families* so they are never double counted;
* conflicting evidence is kept on both sides and surfaced as an explicit conflict record;
* every record points at its source subsystem, the raw observation (step, provider call
  or row) and the engine/provider versions involved.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from app.config import Settings
from app.enums import EvidenceLevel
from app.services.image.lineage import ALGORITHMIC_SOURCE_TYPES
from app.utils.timeparse import as_utc, parse_timestamp

ENGINE_VERSION = "v1"

Kind = Literal["fact", "signal", "unknown", "conflict"]

# Level order, strongest first. Overrides may move a rule *down* this list, never up.
LEVEL_RANK: dict[str, int] = {
    EvidenceLevel.VERIFIED: 4,
    EvidenceLevel.STRONG: 3,
    EvidenceLevel.PROBABLE: 2,
    EvidenceLevel.POSSIBLE: 1,
    EvidenceLevel.UNKNOWN: 0,
}

# docs/07 ceilings: the strongest level a rule may ever produce, whatever the configuration.
# Rules not listed are capped at the level the engine assigns them (i.e. cannot be raised).
LEVEL_CEILING: dict[str, str] = {
    "file.identity": EvidenceLevel.VERIFIED,
    "provenance.valid": EvidenceLevel.VERIFIED,
    "provenance.invalid": EvidenceLevel.POSSIBLE,
    # Signed declarations are the signer's statements: STRONG at most, never VERIFIED.
    "provenance.source-type": EvidenceLevel.STRONG,
    "provenance.training-mining": EvidenceLevel.STRONG,
    "provenance.identity": EvidenceLevel.STRONG,
    "provenance.ingredient.invalid": EvidenceLevel.POSSIBLE,
    "metadata.software": EvidenceLevel.STRONG,
    "metadata.camera": EvidenceLevel.POSSIBLE,
    "metadata.captured": EvidenceLevel.POSSIBLE,
    "metadata.gps": EvidenceLevel.POSSIBLE,
    "metadata.generator": EvidenceLevel.STRONG,
    "metadata.source-type": EvidenceLevel.STRONG,
    "metadata.edit-history": EvidenceLevel.STRONG,
    "matches.exact": EvidenceLevel.VERIFIED,
    "matches.near": EvidenceLevel.POSSIBLE,
    "matches.text.identical": EvidenceLevel.VERIFIED,
    "matches.text.near": EvidenceLevel.POSSIBLE,
    "text.stats": EvidenceLevel.VERIFIED,
    "text.language": EvidenceLevel.PROBABLE,
    "text.hidden": EvidenceLevel.POSSIBLE,
    "text.repetition": EvidenceLevel.POSSIBLE,
    "ai.signal": EvidenceLevel.PROBABLE,
    "sources.matches": EvidenceLevel.POSSIBLE,
    "forensics.multiple": EvidenceLevel.STRONG,
    "forensics.ela.anomaly": EvidenceLevel.POSSIBLE,
    "forensics.compression.offset-grid": EvidenceLevel.POSSIBLE,
    "forensics.compression.prior-jpeg": EvidenceLevel.POSSIBLE,
    "forensics.resampling.detected": EvidenceLevel.POSSIBLE,
    "forensics.noise.anomaly": EvidenceLevel.POSSIBLE,
    "forensics.copy-move.detected": EvidenceLevel.POSSIBLE,
    "forensics.thumbnail.mismatch": EvidenceLevel.POSSIBLE,
    "forensics.thumbnail.region": EvidenceLevel.POSSIBLE,
    "forensics.thumbnail.geometry": EvidenceLevel.POSSIBLE,
    "forensics.double-compression.localized": EvidenceLevel.POSSIBLE,
    "forensics.double-compression.global": EvidenceLevel.POSSIBLE,
}


@dataclass(frozen=True)
class EvidenceThresholds:
    """Every number a rule depends on. Built from settings so deployments can tune them."""

    ai_score_high: float = 0.85
    ai_score_medium: float = 0.6
    fingerprint_near_threshold: int = 10
    text_near_threshold: float = 0.5
    language_probable_confidence: float = 0.9
    # Independent forensic families needed for docs/07 "multiple independent anomalies".
    forensic_families_for_strong: int = 2
    # Default confidence per level when a rule has no better number of its own.
    confidence_verified: float = 1.0
    confidence_strong: float = 0.8
    confidence_probable: float = 0.65
    confidence_possible: float = 0.4
    # rule id -> level; applied after the rules, clamped to LEVEL_CEILING (never stronger).
    level_overrides: dict[str, str] = field(default_factory=dict)
    # Synthesis confidence drops by this much per conflict record.
    conflict_penalty: float = 0.25

    @classmethod
    def from_settings(cls, settings: Settings) -> EvidenceThresholds:
        return cls(
            ai_score_high=settings.ai_score_high,
            ai_score_medium=settings.ai_score_medium,
            fingerprint_near_threshold=settings.fingerprint_near_threshold,
            text_near_threshold=settings.text_near_threshold,
            language_probable_confidence=settings.language_probable_confidence,
            forensic_families_for_strong=settings.forensic_families_for_strong,
            confidence_verified=settings.evidence_confidence_verified,
            confidence_strong=settings.evidence_confidence_strong,
            confidence_probable=settings.evidence_confidence_probable,
            confidence_possible=settings.evidence_confidence_possible,
            level_overrides=dict(settings.evidence_level_overrides),
            conflict_penalty=settings.evidence_conflict_penalty,
        )

    def confidence_for(self, level: str) -> float | None:
        table: dict[str, float | None] = {
            EvidenceLevel.VERIFIED: self.confidence_verified,
            EvidenceLevel.STRONG: self.confidence_strong,
            EvidenceLevel.PROBABLE: self.confidence_probable,
            EvidenceLevel.POSSIBLE: self.confidence_possible,
            EvidenceLevel.UNKNOWN: None,
        }
        return table[level]

    def to_json(self) -> dict[str, Any]:
        """Snapshot recorded with each run so a report can say which thresholds applied."""
        return {
            "ai_score_high": self.ai_score_high,
            "ai_score_medium": self.ai_score_medium,
            "fingerprint_near_threshold": self.fingerprint_near_threshold,
            "text_near_threshold": self.text_near_threshold,
            "language_probable_confidence": self.language_probable_confidence,
            "forensic_families_for_strong": self.forensic_families_for_strong,
            "confidence": {
                "VERIFIED": self.confidence_verified,
                "STRONG": self.confidence_strong,
                "PROBABLE": self.confidence_probable,
                "POSSIBLE": self.confidence_possible,
            },
            "level_overrides": dict(self.level_overrides),
            "conflict_penalty": self.conflict_penalty,
        }


@dataclass(frozen=True)
class EvidenceDraft:
    rule: str  # stable rule id, e.g. "provenance.valid"
    category: str
    level: str
    kind: Kind
    claim: str
    source: str
    confidence: float | None = None
    limitation: str | None = None
    detail: str | None = None
    # Pointers to raw observations: "step:<name>", "provider_call:<id>", "row:<table>".
    refs: list[str] = field(default_factory=list)
    provider_version: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    conflicts_with: list[str] = field(default_factory=list)

    def details_json(self) -> dict[str, Any]:
        """Everything except the columns of the ``evidence`` table, for the ``details`` JSON."""
        return {
            "rule": self.rule,
            "kind": self.kind,
            "limitation": self.limitation,
            "detail": self.detail,
            "refs": list(self.refs),
            "provider_version": self.provider_version,
            "conflicts_with": list(self.conflicts_with),
            "engine_version": ENGINE_VERSION,
            **({"data": self.data} if self.data else {}),
        }


@dataclass
class Observations:
    """Everything the engine may look at for one analysis. ``None`` = subsystem did not run."""

    analysis_type: str
    file: Any | None = None
    metadata: Any | None = None
    provenance: Any | None = None
    fingerprints: Any | None = None
    # (other_analysis_id, relation, score) from the account-level similarity lookup.
    similar_images: Sequence[tuple[Any, str, int]] = ()
    text: Any | None = None
    text_fingerprints: Any | None = None
    similar_texts: Sequence[tuple[Any, str, float]] = ()
    ai: Any | None = None
    search_run: Any | None = None
    search_matches: Sequence[Any] = ()
    forensics: Any | None = None
    provider_calls: Sequence[Any] = ()
    # When the analysis was created (the file's arrival at Verixa); tz-aware.
    submitted_at: datetime | None = None


def _fmt(value: Any) -> str:
    return "?" if value is None else str(value)


def _conf(level: str, t: EvidenceThresholds | None = None) -> float | None:
    return (t or EvidenceThresholds()).confidence_for(level)


def apply_overrides(drafts: list[EvidenceDraft], t: EvidenceThresholds) -> list[EvidenceDraft]:
    """Apply configured per-rule levels. A level can only move *down* from its docs/07 ceiling.

    A record whose confidence was the level default follows the new level's default;
    a record with its own number (an AI score, a language probability) keeps it.
    """
    if not t.level_overrides:
        return drafts
    out: list[EvidenceDraft] = []
    for d in drafts:
        wanted = t.level_overrides.get(d.rule)
        if wanted is None or wanted not in LEVEL_RANK or d.kind == "conflict":
            out.append(d)
            continue
        ceiling = LEVEL_CEILING.get(d.rule, d.level)
        new_level = wanted if LEVEL_RANK[wanted] <= LEVEL_RANK[ceiling] else ceiling
        if new_level == d.level:
            out.append(d)
            continue
        confidence = d.confidence
        if confidence is None or confidence == _conf(d.level, t):
            confidence = _conf(new_level, t)
        out.append(
            replace(
                d,
                level=new_level,
                confidence=confidence,
                data={**d.data, "level_override": {"from": d.level, "to": new_level}},
            )
        )
    return out


def synthesis_confidence(
    records: Sequence[tuple[str, float | None, str]], t: EvidenceThresholds
) -> float:
    """Overall confidence a synthesis may claim: the strongest leveled record, minus conflicts.

    ``records`` are (level, confidence, kind). UNKNOWN records contribute nothing; each
    conflict record subtracts ``t.conflict_penalty`` (docs/07: conflicts lower synthesis
    confidence). Result is clipped to [0, 1].
    """
    best = 0.0
    conflicts = 0
    for level, confidence, kind in records:
        if kind == "conflict":
            conflicts += 1
            continue
        if level == EvidenceLevel.UNKNOWN:
            continue
        best = max(best, float(confidence if confidence is not None else _conf(level, t) or 0.0))
    return round(min(1.0, max(0.0, best - conflicts * t.conflict_penalty)), 4)


def _call_refs(calls: Sequence[Any], operation_prefix: str) -> list[str]:
    return [f"provider_call:{c.id}" for c in calls if str(c.operation).startswith(operation_prefix)]


# -- rule groups --------------------------------------------------------------------------------


def _file_rules(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    f = o.file
    if f is None:
        return []
    if o.analysis_type == "text":
        return [
            EvidenceDraft(
                rule="file.identity",
                category="file",
                level=EvidenceLevel.VERIFIED,
                kind="fact",
                claim=f"The submitted text is {f.size_bytes or '?'} bytes of UTF-8 with SHA-256 "
                f"{f.sha256[:12]}…",
                source="storage",
                confidence=_conf(EvidenceLevel.VERIFIED, t),
                detail="Stored exactly as received; the normalised working copy is hashed "
                "separately.",
                refs=["step:validate", "row:analysis_files"],
                data={"sha256": f.sha256, "size_bytes": f.size_bytes},
            )
        ]
    return [
        EvidenceDraft(
            rule="file.identity",
            category="file",
            level=EvidenceLevel.VERIFIED,
            kind="fact",
            claim=f"The stored file is {f.mime_type or 'of unknown type'}, {f.width or '?'} x "
            f"{f.height or '?'} px, {f.size_bytes or '?'} bytes, SHA-256 {f.sha256[:12]}…",
            source="validation",
            confidence=_conf(EvidenceLevel.VERIFIED, t),
            detail="Type and dimensions were decoded from the content, not read from the name.",
            refs=["step:validate", "step:hashing", "row:analysis_files"],
            data={
                "sha256": f.sha256,
                "mime_type": f.mime_type,
                "width": f.width,
                "height": f.height,
                "size_bytes": f.size_bytes,
            },
        )
    ]


def _remote_reference_rule(o: Observations) -> list[EvidenceDraft]:
    """The file points at a manifest hosted elsewhere (XMP dcterms:provenance, or the engine's
    refusal to fetch it). Verixa never fetches it: the record says so and asserts nothing
    about the remote manifest. One record, whichever side saw the reference."""
    m = o.metadata
    url = (getattr(m, "normalized_json", None) or {}).get("provenance_url") if m else None
    host = (urlsplit(str(url)).hostname or "unknown host") if url else None
    refs = ["step:metadata", "row:image_metadata"]
    source = "xmp"
    p = o.provenance
    engine_json = (getattr(p, "normalized_json", None) or {}) if p is not None else {}
    engine_host = engine_json.get("remote_manifest_host")
    if engine_host and p is not None:
        host = host or str(engine_host)
        refs = ["step:provenance", "row:image_provenance", *refs]
        source = f"c2pa/{p.engine}"
    if not host:
        return []
    return [
        EvidenceDraft(
            rule="provenance.remote",
            category="provenance",
            level=EvidenceLevel.UNKNOWN,
            kind="unknown",
            claim=f"The file references a remote Content Credentials manifest at {host}.",
            source=source,
            detail="Verixa does not fetch remote manifests; only the reference is recorded.",
            limitation="Nothing about the referenced manifest is asserted: it may or may not "
            "exist, validate, or describe this file.",
            refs=refs,
            data={"host": host},
        )
    ]


def _provenance_rules(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    p = o.provenance
    refs = ["step:provenance", *_call_refs(o.provider_calls, "provenance.")]
    remote = _remote_reference_rule(o)
    if p is None:
        return [
            EvidenceDraft(
                rule="provenance.uninspected",
                category="provenance",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="Content credentials were not inspected.",
                source="c2pa",
                limitation="No C2PA engine ran for this analysis.",
                refs=["step:provenance"],
            ),
            *remote,
        ]
    n = p.normalized_json or {}
    src = f"c2pa/{p.engine}"
    if not p.has_c2pa and n.get("manifest_location") == "remote":
        return remote  # the reference is the whole story; "absent" would misdescribe it
    if not p.has_c2pa:
        return [
            EvidenceDraft(
                rule="provenance.absent",
                category="provenance",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="No content credentials (C2PA) are embedded in this file.",
                source=src,
                limitation="Absence does not establish whether the file was edited or generated; "
                "most images carry none.",
                refs=refs,
                provider_version=p.engine_version,
            ),
            *remote,
        ]
    assertions = n.get("assertions") or {}
    hash_data = assertions.get("hash_data") or {}
    agents = n.get("software_agents") or []
    if p.valid_signature:
        head = EvidenceDraft(
            rule="provenance.valid",
            category="provenance",
            level=EvidenceLevel.VERIFIED,
            kind="fact",
            claim="A C2PA manifest is present and its signature validates (issuer as stated: "
            f"{p.signer or 'unknown'}).",
            source=src,
            confidence=_conf(EvidenceLevel.VERIFIED, t),
            detail=_provenance_detail(p.claim_generator, hash_data),
            limitation="Validity shows the manifest is intact, not that its claims are true; "
            "issuer trust is not evaluated.",
            refs=refs,
            provider_version=p.engine_version,
            data={
                "signer": p.signer,
                "signed_at": p.signed_at,
                "claim_generator": p.claim_generator,
                "actions": n.get("actions") or [],
                **(
                    {
                        "hash_coverage": {
                            "algorithm": hash_data.get("alg"),
                            "excluded_ranges": hash_data.get("exclusion_count"),
                        }
                    }
                    if hash_data
                    else {}
                ),
                **({"software_agents": agents} if agents else {}),
            },
        )
    else:
        failures = [str(x.get("code")) for x in (n.get("validation_failures") or []) if x]
        head = EvidenceDraft(
            rule="provenance.invalid",
            category="provenance",
            level=EvidenceLevel.POSSIBLE,
            kind="signal",
            claim="A C2PA manifest is present but validation reported problems.",
            source=src,
            confidence=_conf(EvidenceLevel.POSSIBLE, t),
            detail=", ".join(failures) or None,
            limitation="The manifest may be damaged, or the file changed after signing.",
            refs=refs,
            provider_version=p.engine_version,
            data={"validation_failures": failures},
        )
    return [head, *_provenance_declaration_rules(p, n, src, refs, t), *remote]


def _provenance_detail(claim_generator: str | None, hash_data: dict[str, Any]) -> str | None:
    parts = []
    if claim_generator:
        parts.append(f"Claim generator: {claim_generator}.")
    if hash_data:
        excluded = hash_data.get("exclusion_count") or 0
        parts.append(
            f"The signature covers the file bytes ({hash_data.get('alg') or 'hash'}) except "
            f"{excluded} excluded range(s), normally the manifest itself."
        )
    return " ".join(parts) or None


def _provenance_declaration_rules(
    p: Any, n: dict[str, Any], src: str, refs: list[str], t: EvidenceThresholds
) -> list[EvidenceDraft]:
    """What the signer *declared* (source type, permitted use, identity) and what the
    ingredient tree records. Declarations cap at STRONG when the signature validates and
    drop to POSSIBLE when it does not; they are never VERIFIED."""
    out: list[EvidenceDraft] = []
    assertions = n.get("assertions") or {}
    intact = bool(p.valid_signature)
    declared_level = EvidenceLevel.STRONG if intact else EvidenceLevel.POSSIBLE
    declared_caveat = (
        "" if intact else " The signature did not validate, so this declaration is unverified."
    )

    source_types = assertions.get("source_types") or []
    if source_types:
        # The most specific declaration wins: any algorithmic type over a capture type.
        algorithmic_entries = [
            s for s in source_types if s.get("short") in ALGORITHMIC_SOURCE_TYPES
        ]
        chosen = (algorithmic_entries or source_types)[0]
        short = chosen.get("short") or chosen.get("uri")
        algorithmic = bool(algorithmic_entries)
        level = declared_level if algorithmic else EvidenceLevel.POSSIBLE
        out.append(
            EvidenceDraft(
                rule="provenance.source-type",
                category="provenance",
                level=level,
                kind="signal",
                claim=f'The signed manifest declares the digital source type "{short}"'
                + (f" for the action {chosen.get('action')}" if chosen.get("action") else "")
                + (" (algorithmic / AI-generated, as declared)." if algorithmic else "."),
                source=src,
                confidence=_conf(level, t),
                limitation="A declared source type is the signer's statement, not a measurement: "
                "verified as stated, not as true." + declared_caveat,
                refs=refs,
                provider_version=p.engine_version,
                data={
                    "digital_source_type": short,
                    "uri": chosen.get("uri"),
                    "algorithmic": algorithmic,
                    "action": chosen.get("action"),
                    "declared_types": [s.get("short") for s in source_types],
                },
            )
        )

    training = assertions.get("training_mining") or {}
    if training:
        summary = ", ".join(f"{k}: {v}" for k, v in sorted(training.items()))
        out.append(
            EvidenceDraft(
                rule="provenance.training-mining",
                category="provenance",
                level=declared_level,
                kind="signal",
                claim="The signed manifest declares permitted uses for AI training and data "
                "mining.",
                source=src,
                confidence=_conf(declared_level, t),
                detail=summary,
                limitation="A permitted-use declaration; it is not enforced and says nothing "
                "about how the content was made." + declared_caveat,
                refs=refs,
                provider_version=p.engine_version,
                data={"entries": training},
            )
        )

    identity = assertions.get("identity") or {}
    if identity.get("present"):
        codes = _identity_codes(n)
        validated = "cawg.ica.credential_valid" in codes or "cawg.identity.validated" in codes
        level = declared_level if validated else EvidenceLevel.POSSIBLE
        out.append(
            EvidenceDraft(
                rule="provenance.identity",
                category="provenance",
                level=level,
                kind="signal",
                claim="The manifest carries a creator identity assertion (CAWG)"
                + (" that the engine validated." if validated else " that was not validated."),
                source=src,
                confidence=_conf(level, t),
                detail=", ".join(identity.get("names") or []) or None,
                limitation="Identity credentials are validated against the engine's own identity "
                "trust list, not by Verixa; a name is what the credential issuer recorded."
                + declared_caveat,
                refs=refs,
                provider_version=p.engine_version,
                data={"kind": identity.get("kind"), "codes": codes, "validated": validated},
            )
        )

    failed = int(n.get("ingredient_failures") or 0)
    if failed:
        out.append(
            EvidenceDraft(
                rule="provenance.ingredient.invalid",
                category="provenance",
                level=EvidenceLevel.POSSIBLE,
                kind="signal",
                claim=f"{failed} ingredient(s) in the manifest carry validation failures.",
                source=src,
                confidence=_conf(EvidenceLevel.POSSIBLE, t),
                limitation="Ingredient failures were recorded by the signer at composition time; "
                "the active manifest itself may still validate.",
                refs=refs,
                provider_version=p.engine_version,
                data={
                    "ingredient_failures": failed,
                    "ingredient_count": p.ingredient_count
                    if hasattr(p, "ingredient_count")
                    else n.get("ingredient_count"),
                },
            )
        )
    return out


def _identity_codes(n: dict[str, Any]) -> list[str]:
    codes = [c for c in (n.get("validation_codes") or []) if str(c).startswith("cawg.")]
    validation = n.get("validation") or {}
    for family in ("success", "informational", "failure"):
        for c in (validation.get("active_manifest") or {}).get(family) or []:
            if str(c).startswith("cawg.") and c not in codes:
                codes.append(c)
    return codes


def _metadata_rules(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    m = o.metadata
    if m is None:
        return [
            EvidenceDraft(
                rule="metadata.unavailable",
                category="metadata",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="Metadata was not extracted.",
                source="metadata",
                refs=["step:metadata"],
            )
        ]
    n = m.normalized_json or {}
    src = f"metadata/{m.engine}"
    refs = ["step:metadata", "row:image_metadata", *_call_refs(o.provider_calls, "metadata.")]
    out: list[EvidenceDraft] = []
    if m.software:
        out.append(
            EvidenceDraft(
                rule="metadata.software",
                category="metadata",
                level=EvidenceLevel.STRONG,
                kind="signal",
                claim=f'Metadata records the software "{m.software}".',
                source=src,
                confidence=_conf(EvidenceLevel.STRONG, t),
                limitation="A software tag shows what wrote the metadata, not the full edit "
                "history; tags can be altered.",
                refs=refs,
                provider_version=m.engine_version,
                data={"software": m.software},
            )
        )
    if m.camera_make or m.camera_model:
        camera = " ".join(x for x in (m.camera_make, m.camera_model) if x)
        out.append(
            EvidenceDraft(
                rule="metadata.camera",
                category="metadata",
                level=EvidenceLevel.POSSIBLE,
                kind="signal",
                claim=f'Metadata records the camera "{camera}".',
                source=src,
                confidence=_conf(EvidenceLevel.POSSIBLE, t),
                limitation="Camera fields are recorded values and can be copied or edited.",
                refs=refs,
                provider_version=m.engine_version,
                data={"camera_make": m.camera_make, "camera_model": m.camera_model},
            )
        )
    captured = n.get("captured_at")
    if captured and captured.get("raw"):
        tz = "" if captured.get("tz_known") else " (timezone not recorded)"
        out.append(
            EvidenceDraft(
                rule="metadata.captured",
                category="metadata",
                level=EvidenceLevel.POSSIBLE,
                kind="signal",
                claim=f"Metadata records a capture time of {captured['raw']}{tz}.",
                source=src,
                confidence=_conf(EvidenceLevel.POSSIBLE, t),
                limitation="Device clocks and edits can make recorded times wrong.",
                refs=refs,
                provider_version=m.engine_version,
                data={"captured_at": captured},
            )
        )
    generator = n.get("generator")
    signals = n.get("generator_signals") or []
    if generator and signals:
        tags = sorted({str(s.get("tag")) for s in signals})
        out.append(
            EvidenceDraft(
                rule="metadata.generator",
                category="metadata",
                level=EvidenceLevel.STRONG,
                kind="signal",
                claim=f'Metadata carries generator markers naming "{generator}".',
                source=src,
                confidence=_conf(EvidenceLevel.STRONG, t),
                detail="Found in " + ", ".join(tags) + ".",
                limitation="Generator markers show what software wrote the file's metadata; "
                "they can be stripped, copied or forged, and their absence proves nothing.",
                refs=refs,
                provider_version=m.engine_version,
                data={"generator": generator, "tags": tags, "signals": signals[:5]},
            )
        )
    source_type = n.get("digital_source_type")
    if source_type:
        algorithmic = source_type in ALGORITHMIC_SOURCE_TYPES
        out.append(
            EvidenceDraft(
                rule="metadata.source-type",
                category="metadata",
                level=EvidenceLevel.STRONG if algorithmic else EvidenceLevel.POSSIBLE,
                kind="signal",
                claim=(
                    f'Metadata declares the IPTC digital source type "{source_type}"'
                    + (" (algorithmic / AI-generated, as declared)." if algorithmic else ".")
                ),
                source=src,
                confidence=_conf(
                    EvidenceLevel.STRONG if algorithmic else EvidenceLevel.POSSIBLE, t
                ),
                limitation="A declared source type is the producer's statement, not a measurement.",
                refs=refs,
                provider_version=m.engine_version,
                data={"digital_source_type": source_type, "algorithmic": algorithmic},
            )
        )
    history = n.get("edit_history") or []
    if history or n.get("derived_from_document_id"):
        agents = sorted({str(e.get("software")) for e in history if e.get("software")})
        actions = [str(e.get("action")) for e in history]
        derived = n.get("derived_from_document_id")
        parts = []
        if history:
            parts.append(
                f"XMP edit history records {len(history)} action"
                + ("s" if len(history) != 1 else "")
                + (" by " + ", ".join(agents) if agents else "")
            )
        if derived:
            parts.append("the file is recorded as derived from another document")
        out.append(
            EvidenceDraft(
                rule="metadata.edit-history",
                category="metadata",
                level=EvidenceLevel.STRONG,
                kind="signal",
                claim=(lambda text: text[:1].upper() + text[1:] + ".")("; ".join(parts)),
                source=src,
                confidence=_conf(EvidenceLevel.STRONG, t),
                detail=", ".join(actions[:12]) or None,
                limitation="Edit history is written by editors that choose to record it; it can "
                "be incomplete, removed or fabricated, and says nothing about what changed.",
                refs=refs,
                provider_version=m.engine_version,
                data={
                    "actions": actions,
                    "software_agents": agents,
                    "document_id": n.get("document_id"),
                    "original_document_id": n.get("original_document_id"),
                    "derived_from_document_id": derived,
                },
            )
        )
    if n.get("gps_present"):
        has_fix = n.get("gps_latitude") is not None and n.get("gps_longitude") is not None
        gps_when = n.get("gps_time") or {}
        out.append(
            EvidenceDraft(
                rule="metadata.gps",
                category="metadata",
                level=EvidenceLevel.POSSIBLE,
                kind="signal",
                # Coordinates stay in `data` (shown in the report, never sent to a model).
                claim=(
                    "Metadata records GPS coordinates."
                    if has_fix
                    else "Metadata contains GPS fields but no usable coordinates."
                ),
                source=src,
                confidence=_conf(EvidenceLevel.POSSIBLE, t),
                limitation=(
                    "GPS tags are written by software and can be inaccurate, stale or "
                    "fabricated; they show where the device claims it was, not where the "
                    "picture was taken."
                ),
                refs=refs,
                provider_version=m.engine_version,
                data={
                    "latitude": n.get("gps_latitude"),
                    "longitude": n.get("gps_longitude"),
                    "altitude_m": n.get("gps_altitude_m"),
                    "gps_time": gps_when.get("raw"),
                },
            )
        )
    # PNG text chunks with generator markers are metadata too: "none" would contradict them.
    if not (n.get("has_exif") or n.get("has_xmp") or n.get("has_iptc") or signals):
        out.append(
            EvidenceDraft(
                rule="metadata.none",
                category="metadata",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="No EXIF, XMP or IPTC metadata is present.",
                source=src,
                limitation="Missing metadata does not establish editing; many platforms strip "
                "it on upload.",
                refs=refs,
                provider_version=m.engine_version,
            )
        )
    return out


def _image_match_rules(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    if o.fingerprints is None:
        return []
    exact = [s for s in o.similar_images if s[1] == "exact"]
    near = [s for s in o.similar_images if s[1] == "near"]
    out: list[EvidenceDraft] = []
    refs = ["step:hashing", "row:image_fingerprints"]
    if exact:
        out.append(
            EvidenceDraft(
                rule="matches.exact",
                category="matches",
                level=EvidenceLevel.VERIFIED,
                kind="fact",
                claim=f"{len(exact)} of your other analyses contain byte-identical content "
                "(same SHA-256).",
                source="fingerprints",
                confidence=_conf(EvidenceLevel.VERIFIED, t),
                limitation="Identity of bytes says nothing about which copy came first.",
                refs=refs,
                data={"analysis_ids": [str(s[0]) for s in exact]},
            )
        )
    if near:
        out.append(
            EvidenceDraft(
                rule="matches.near",
                category="matches",
                level=EvidenceLevel.POSSIBLE,
                kind="signal",
                claim=f"{len(near)} of your other analyses look perceptually similar (pHash/dHash "
                f"within {t.fingerprint_near_threshold} bits).",
                source="fingerprints",
                confidence=_conf(EvidenceLevel.POSSIBLE, t),
                limitation="Perceptual similarity can come from recompression, resizing or "
                "unrelated look-alikes.",
                refs=refs,
                data={
                    "analysis_ids": [str(s[0]) for s in near],
                    "threshold_bits": t.fingerprint_near_threshold,
                },
            )
        )
    return out


def _text_rules(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    tx = o.text
    if tx is None:
        return [
            EvidenceDraft(
                rule="text.unprocessed",
                category="text",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="Text statistics are not available.",
                source="text",
                refs=["step:normalize", "step:statistics"],
            )
        ]
    out: list[EvidenceDraft] = []
    st = tx.statistics_json or {}
    out.append(
        EvidenceDraft(
            rule="text.stats",
            category="text",
            level=EvidenceLevel.VERIFIED,
            kind="fact",
            claim=f"{tx.word_count or 0:,} words, {tx.sentence_count or 0:,} sentences, "
            f"{tx.paragraph_count or 0:,} paragraphs.",
            source="statistics",
            confidence=_conf(EvidenceLevel.VERIFIED, t),
            detail="Deterministic counts over the normalised text.",
            refs=["step:statistics", "row:text_analysis"],
            data={
                "word_count": tx.word_count,
                "sentence_count": tx.sentence_count,
                "paragraph_count": tx.paragraph_count,
            },
        )
    )
    lang = tx.language_json or {}
    engine = lang.get("engine") or "language"
    if tx.language:
        conf = float(tx.language_confidence or 0.0)
        level = (
            EvidenceLevel.PROBABLE
            if conf >= t.language_probable_confidence
            else EvidenceLevel.POSSIBLE
        )
        out.append(
            EvidenceDraft(
                rule="text.language",
                category="text",
                level=level,
                kind="signal",
                claim=f'The text is most likely written in "{tx.language}" (p≈{conf:.2f}).',
                source=f"language/{engine}",
                confidence=round(conf, 4),
                limitation="Statistical detection; short or mixed-language texts are often "
                "misclassified.",
                refs=["step:language", "row:text_analysis"],
                data={"language": tx.language, "confidence": conf},
            )
        )
    else:
        out.append(
            EvidenceDraft(
                rule="text.language.unknown",
                category="text",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="The language could not be determined.",
                source="language",
                limitation=lang.get("reason"),
                refs=["step:language"],
            )
        )
    norm = tx.normalization_json or {}
    hidden = sum(
        int(norm.get(k) or 0)
        for k in ("zero_width_removed", "bidi_controls_removed", "control_chars_removed")
    )
    if hidden > 0:
        out.append(
            EvidenceDraft(
                rule="text.hidden",
                category="text",
                level=EvidenceLevel.POSSIBLE,
                kind="signal",
                claim=f"{hidden} hidden or control characters were present in the original text.",
                source="normalize",
                confidence=_conf(EvidenceLevel.POSSIBLE, t),
                limitation="Such characters can come from ordinary copy-paste, but also from "
                "watermarking or obfuscation.",
                refs=["step:normalize", "row:text_analysis"],
                data={"hidden_characters": hidden},
            )
        )
    repeated = int(st.get("repeated_sentence_count") or 0)
    if repeated > 0:
        out.append(
            EvidenceDraft(
                rule="text.repetition",
                category="text",
                level=EvidenceLevel.POSSIBLE,
                kind="signal",
                claim=f"{repeated} sentence(s) are repeated verbatim.",
                source="statistics",
                confidence=_conf(EvidenceLevel.POSSIBLE, t),
                limitation="Repetition is a stylistic observation, not evidence of machine "
                "authorship.",
                refs=["step:statistics", "row:text_analysis"],
                data={"repeated_sentence_count": repeated},
            )
        )
    return out


def _text_match_rules(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    if o.text_fingerprints is None:
        return []
    identical = [s for s in o.similar_texts if s[1] != "near"]
    near = [s for s in o.similar_texts if s[1] == "near"]
    refs = ["step:fingerprints", "row:text_fingerprints"]
    out: list[EvidenceDraft] = []
    if identical:
        out.append(
            EvidenceDraft(
                rule="matches.text.identical",
                category="matches",
                level=EvidenceLevel.VERIFIED,
                kind="fact",
                claim=f"{len(identical)} of your other text analyses contain the same text "
                "(identical bytes, or identical after normalisation / ignoring case and "
                "punctuation).",
                source="fingerprints",
                confidence=_conf(EvidenceLevel.VERIFIED, t),
                limitation="Identity says nothing about which copy came first.",
                refs=refs,
                data={"analysis_ids": [str(s[0]) for s in identical]},
            )
        )
    if near:
        out.append(
            EvidenceDraft(
                rule="matches.text.near",
                category="matches",
                level=EvidenceLevel.POSSIBLE,
                kind="signal",
                claim=f"{len(near)} of your other text analyses share many 5-word sequences "
                f"(estimated Jaccard ≥ {t.text_near_threshold:.2f}).",
                source="fingerprints",
                confidence=_conf(EvidenceLevel.POSSIBLE, t),
                limitation="Shared phrasing can come from quotation, templates or common idiom, "
                "not only copying.",
                refs=refs,
                data={
                    "analysis_ids": [str(s[0]) for s in near],
                    "threshold": t.text_near_threshold,
                },
            )
        )
    return out


def ai_level(score: float | None, *, calibrated: bool, t: EvidenceThresholds) -> str:
    """docs/07: a *calibrated* high score is PROBABLE; uncalibrated high and medium are POSSIBLE."""
    if score is None:
        return EvidenceLevel.UNKNOWN
    if score >= t.ai_score_high:
        return EvidenceLevel.PROBABLE if calibrated else EvidenceLevel.POSSIBLE
    if score >= t.ai_score_medium:
        return EvidenceLevel.POSSIBLE
    return EvidenceLevel.UNKNOWN


def _ai_rules(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    ai = o.ai
    if ai is None:
        return [
            EvidenceDraft(
                rule="ai.unavailable",
                category="ai",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="AI-generation signals were not evaluated.",
                source="ai-detector",
                limitation="No detector is configured. Detector output is never proof of "
                "authorship.",
                refs=["step:ai"],
            )
        ]
    src = f"ai/{ai.provider}:{ai.model}@{ai.provider_version}"
    refs = ["step:ai", "row:ai_detections", *_call_refs(o.provider_calls, "ai.")]
    if ai.score is None:
        return [
            EvidenceDraft(
                rule="ai.noscore",
                category="ai",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="The AI detector returned no usable score.",
                source=src,
                refs=refs,
                provider_version=ai.provider_version,
            )
        ]
    level = ai_level(ai.score, calibrated=bool(ai.calibrated), t=t)
    pct = round(ai.score * 100)
    data = {
        "score": ai.score,
        "label": ai.label,
        "calibrated": bool(ai.calibrated),
        "thresholds": {"high": t.ai_score_high, "medium": t.ai_score_medium},
    }
    if level == EvidenceLevel.UNKNOWN:
        return [
            EvidenceDraft(
                rule="ai.weak",
                category="ai",
                level=level,
                kind="signal",
                claim=f"The AI detector reported a weak signal ({pct}/100, below the medium "
                "threshold).",
                source=src,
                confidence=round(float(ai.score), 4),
                limitation="A low score does not establish human authorship; detectors miss "
                "much AI text and imagery.",
                refs=refs,
                provider_version=ai.provider_version,
                data=data,
            )
        ]
    strength = "strong" if ai.score >= t.ai_score_high else "medium"
    if ai.calibrated:
        limitation = (
            "Detector scores have known false-positive and false-negative rates; this is not "
            "proof of AI authorship."
        )
    else:
        limitation = (
            "The score is not calibrated, so a high value is treated as POSSIBLE rather than "
            "PROBABLE; detector output is never proof of AI authorship."
        )
    return [
        EvidenceDraft(
            rule="ai.signal",
            category="ai",
            level=level,
            kind="signal",
            claim=f"The AI detector reported a {strength} AI-generation signal ({pct}/100).",
            source=src,
            confidence=round(float(ai.score), 4),
            limitation=limitation,
            refs=refs,
            provider_version=ai.provider_version,
            data=data,
        )
    ]


def _source_rules(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    kind = "reverse-image" if o.analysis_type == "image" else "phrase"
    run = o.search_run
    if run is None:
        return [
            EvidenceDraft(
                rule="sources.unavailable",
                category="sources",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim=f"No {kind} search was performed.",
                source="search",
                limitation="No source-search provider is configured.",
                refs=["step:search"],
            )
        ]
    src = f"search/{run.provider}@{run.provider_version}"
    refs = ["step:search", "row:source_search_runs", *_call_refs(o.provider_calls, "search.")]
    matches = list(o.search_matches)
    if not matches:
        return [
            EvidenceDraft(
                rule="sources.none",
                category="sources",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim=f"The {kind} search returned no matches.",
                source=src,
                limitation="The provider's index is not the whole web; no matches is not "
                "evidence of originality.",
                refs=refs,
                provider_version=run.provider_version,
            )
        ]
    dated = sum(1 for m in matches if m.published_at)
    noun = "source" if len(matches) == 1 else "sources"
    dated_note = f" ({dated} with a reported date)" if dated else ""
    limitation = (
        "Shared wording can come from quotation, common phrasing or the same upstream source; "
        "a phrase match is not plagiarism."
        if kind == "phrase"
        else "A reverse-image hit shows where similar content was found, not where it came "
        "from or which copy is earlier."
    )
    return [
        EvidenceDraft(
            rule="sources.matches",
            category="sources",
            level=EvidenceLevel.POSSIBLE,
            kind="signal",
            claim=f"The {kind} search found {len(matches)} similar {noun}{dated_note}.",
            source=src,
            confidence=_conf(EvidenceLevel.POSSIBLE, t),
            limitation=limitation,
            refs=refs,
            provider_version=run.provider_version,
            data={
                "match_count": len(matches),
                "dated": dated,
                "urls": [m.url for m in matches[:10]],
            },
        )
    ]


def _forensic_rules(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    f = o.forensics
    if f is None:
        return [
            EvidenceDraft(
                rule="forensics.unavailable",
                category="forensics",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="Forensic analysis was not run.",
                source="forensics",
                refs=["step:ela"],
            )
        ]
    out: list[EvidenceDraft] = []
    families: list[str] = []

    def method(name: str) -> dict[str, Any] | None:
        j = getattr(f, f"{name}_json", None)
        return j if isinstance(j, dict) else None

    def applicable(j: dict[str, Any] | None) -> dict[str, Any] | None:
        return j if j and j.get("applicable") else None

    # -- ELA --------------------------------------------------------------------------------
    ela_raw = method("ela")
    ela = applicable(ela_raw)
    if ela_raw and not ela:
        out.append(
            EvidenceDraft(
                rule="forensics.ela.na",
                category="forensics",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="Error Level Analysis is not applicable to this file format.",
                source="ela",
                detail=ela_raw.get("reason"),
                refs=["step:ela", "row:image_forensics"],
            )
        )
    elif ela and ela.get("anomaly"):
        regions = ela.get("regions") or []
        r = regions[0] if regions else None
        out.append(
            EvidenceDraft(
                rule="forensics.ela.anomaly",
                category="forensics",
                level=EvidenceLevel.POSSIBLE,
                kind="signal",
                claim=f"ELA shows {len(regions)} localised region(s) re-compressing differently "
                "from the rest of the image.",
                source="ela",
                confidence=_conf(EvidenceLevel.POSSIBLE, t),
                detail=(
                    f"Largest region at ({r['x']}, {r['y']}), {r['width']} x {r['height']} px; "
                    f"{float(ela.get('outlier_block_fraction') or 0) * 100:.1f}% of blocks are "
                    "outliers."
                    if r
                    else None
                ),
                limitation="ELA is a heuristic: sharp detail, text and saturated colour produce "
                "the same pattern. This is not proof of editing.",
                refs=["step:ela", "row:image_forensics"],
                provider_version=ela.get("version"),
                data={"regions": regions, "family": "error-level/compression"},
            )
        )
    elif ela:
        out.append(
            EvidenceDraft(
                rule="forensics.ela.none",
                category="forensics",
                level=EvidenceLevel.UNKNOWN,
                kind="signal",
                claim="ELA found no localised error-level pattern.",
                source="ela",
                detail=ela.get("observation"),
                limitation="Absence of an ELA pattern is not evidence of no editing; whole-image "
                "resaves and same-quality edits leave no trace.",
                refs=["step:ela", "row:image_forensics"],
                provider_version=ela.get("version"),
            )
        )

    # -- compression (same family as ELA) -----------------------------------------------------
    c = applicable(method("compression"))
    if c:
        grid = c.get("grid") or {}
        enc = c.get("encoding")
        refs = ["step:compression", "row:image_forensics"]
        if c.get("anomaly"):
            out.append(
                EvidenceDraft(
                    rule="forensics.compression.offset-grid",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim=f"A second JPEG block grid offset by ({grid.get('offset_x')}, "
                    f"{grid.get('offset_y')}) px is detectable.",
                    source="compression",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail="Consistent with cropping or shifting after an earlier JPEG save, then "
                    "saving again. Repeating texture can produce the same pattern.",
                    limitation="Correlated with ELA; not an independent indicator. Crop-and-resave "
                    "is a routine, legitimate workflow.",
                    refs=refs,
                    provider_version=c.get("version"),
                    data={"grid": grid, "family": "error-level/compression"},
                )
            )
        elif c.get("prior_jpeg_grid"):
            out.append(
                EvidenceDraft(
                    rule="forensics.compression.prior-jpeg",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim=f"This {c.get('format')} file carries an 8x8 JPEG-style block grid.",
                    source="compression",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail="The content was probably JPEG-compressed before being saved in its "
                    "current format.",
                    limitation="Says something about the file's history, not about editing. "
                    "Scaling or texture can mimic a grid.",
                    refs=refs,
                    provider_version=c.get("version"),
                    data={"grid": grid, "format": c.get("format")},
                )
            )
        elif enc:
            out.append(
                EvidenceDraft(
                    rule="forensics.compression.encoding",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="signal",
                    claim="Last saved as a "
                    f"{'progressive' if enc.get('progressive') else 'baseline'} JPEG, "
                    f"{enc.get('subsampling') or 'unknown'} subsampling, "
                    f"{'standard' if enc.get('standard_tables') else 'custom'} tables at "
                    f"quality ≈ {_fmt(enc.get('estimated_quality'))}.",
                    source="compression",
                    detail="Encoder settings of the most recent save. They do not indicate "
                    "editing.",
                    refs=refs,
                    provider_version=c.get("version"),
                    data={"encoding": enc},
                )
            )
        else:
            out.append(
                EvidenceDraft(
                    rule="forensics.compression.none",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="signal",
                    claim=f"{c.get('format')} container; no JPEG block grid stands out.",
                    source="compression",
                    detail=c.get("observation"),
                    refs=refs,
                    provider_version=c.get("version"),
                )
            )
    if (ela and ela.get("anomaly")) or (c and c.get("anomaly")):
        families.append("error-level/compression")

    # -- resampling (processing history; never an anomaly) -------------------------------------
    r = applicable(method("resampling"))
    if r:
        refs = ["step:resampling", "row:image_forensics"]
        if r.get("detected"):
            peaks = r.get("peaks") or []
            p = peaks[0] if peaks else None
            out.append(
                EvidenceDraft(
                    rule="forensics.resampling.detected",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim="Periodic pixel correlations consistent with the picture having been "
                    "rescaled or rotated.",
                    source="resampling",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail=(
                        f"{len(peaks)} spectral peak(s); strongest {p['ratio']}x its surroundings "
                        f"at ({p['fx']}, {p['fy']}) cycles/px."
                        if p
                        else None
                    ),
                    limitation="Resizing for the web or by a camera pipeline leaves the same "
                    "trace. This says the image was resampled at some point, not that it was "
                    "edited.",
                    refs=refs,
                    provider_version=r.get("version"),
                    data={"peaks": peaks},
                )
            )
        elif r.get("measured"):
            out.append(
                EvidenceDraft(
                    rule="forensics.resampling.none",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="signal",
                    claim="No global resampling trace stands out.",
                    source="resampling",
                    detail=r.get("observation"),
                    limitation="Downscaling, strong compression and some scale factors leave no "
                    "detectable trace.",
                    refs=refs,
                    provider_version=r.get("version"),
                )
            )
        else:
            out.append(
                EvidenceDraft(
                    rule="forensics.resampling.unmeasured",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="unknown",
                    claim="The image is too small for a resampling measurement.",
                    source="resampling",
                    refs=refs,
                )
            )

    # -- noise (independent family) ------------------------------------------------------------
    n = applicable(method("noise"))
    if n:
        refs = ["step:noise", "row:image_forensics"]
        if n.get("anomaly"):
            regions = n.get("regions") or []
            reg = regions[0] if regions else None
            out.append(
                EvidenceDraft(
                    rule="forensics.noise.anomaly",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim=f"Noise level differs from the rest of the image in {len(regions)} "
                    "compact region(s).",
                    source="noise",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail=(
                        f"Baseline about {n.get('baseline_sigma')} grey levels; largest region at "
                        f"({reg['x']}, {reg['y']}), {reg['width']} x {reg['height']} px, about "
                        f"{reg['sigma']}."
                        if reg
                        else None
                    ),
                    limitation="Depth of field, sky versus foliage and in-camera denoising produce "
                    "the same differences. Not proof of editing.",
                    refs=refs,
                    provider_version=n.get("version"),
                    data={"regions": regions, "family": "noise"},
                )
            )
            families.append("noise")
        elif n.get("measured") and int(n.get("blocks_smooth") or 0) > 0:
            out.append(
                EvidenceDraft(
                    rule="forensics.noise.consistent",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="signal",
                    claim="Noise level is consistent across the smooth areas that could be "
                    "compared.",
                    source="noise",
                    detail=n.get("observation"),
                    limitation="Only smooth areas are compared; strong compression flattens noise "
                    "and hides differences.",
                    refs=refs,
                    provider_version=n.get("version"),
                )
            )
        else:
            out.append(
                EvidenceDraft(
                    rule="forensics.noise.unmeasured",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="unknown",
                    claim="Noise consistency could not be measured.",
                    source="noise",
                    detail=n.get("observation"),
                    refs=refs,
                )
            )

    # -- copy-move (independent family) --------------------------------------------------------
    cm = applicable(method("copy_move"))
    if cm:
        refs = ["step:copy_move", "row:image_forensics"]
        if cm.get("detected"):
            matches = cm.get("matches") or []
            m = matches[0] if matches else None
            out.append(
                EvidenceDraft(
                    rule="forensics.copy-move.detected",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim=f"{len(matches)} region(s) of the image reappear elsewhere in the same "
                    "image, shifted by a constant offset.",
                    source="copy_move",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail=(
                        f"Largest: {m['width']} x {m['height']} px at ({m['source_x']}, "
                        f"{m['source_y']}) reappears at ({m['target_x']}, {m['target_y']}); "
                        f"{m['pairs']} matching block pairs."
                        if m
                        else None
                    ),
                    limitation="Tiles, brickwork, text and identical products repeat "
                    "legitimately. Consistent with cloning, not proof of it.",
                    refs=refs,
                    provider_version=cm.get("version"),
                    data={"matches": matches, "family": "copy-move"},
                )
            )
            families.append("copy-move")
        elif cm.get("measured"):
            out.append(
                EvidenceDraft(
                    rule="forensics.copy-move.none",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="signal",
                    claim="No translated duplicate regions were found.",
                    source="copy_move",
                    detail=cm.get("observation"),
                    limitation="Rotated, scaled or retouched copies and clones inside flat areas "
                    "are not detected.",
                    refs=refs,
                    provider_version=cm.get("version"),
                )
            )
        else:
            out.append(
                EvidenceDraft(
                    rule="forensics.copy-move.unmeasured",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="unknown",
                    claim="The image is too small for block matching.",
                    source="copy_move",
                    refs=refs,
                )
            )

    # -- double compression (JPEG ghosts; local ghosts share the ELA/compression family) -------
    dc_raw = method("double_compression")
    dcj = applicable(dc_raw)
    if dc_raw and not dcj:
        out.append(
            EvidenceDraft(
                rule="forensics.double-compression.na",
                category="forensics",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="JPEG ghost analysis is not applicable to this file format.",
                source="double_compression",
                detail=dc_raw.get("reason"),
                refs=["step:double_compression", "row:image_forensics"],
            )
        )
    elif dcj:
        refs = ["step:double_compression", "row:image_forensics"]
        if dcj.get("anomaly"):
            regions = dcj.get("regions") or []
            r = regions[0] if regions else None
            out.append(
                EvidenceDraft(
                    rule="forensics.double-compression.localized",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim=f"{len(regions)} region(s) carry a JPEG ghost of an earlier compression "
                    f"(about quality {dcj.get('ghost_quality_local')}) that the rest of the image "
                    "does not.",
                    source="double_compression",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail=(
                        f"Largest region at ({r['x']}, {r['y']}), {r['width']} x {r['height']} px; "
                        f"{float(dcj.get('ghost_block_fraction') or 0) * 100:.1f}% of blocks carry "
                        "the ghost."
                        if r
                        else None
                    ),
                    limitation="Consistent with a region pasted from a lower-quality JPEG; strong "
                    "texture boundaries can mimic it. Correlated with ELA, not independent of it.",
                    refs=refs,
                    provider_version=dcj.get("version"),
                    data={"regions": regions, "family": "error-level/compression"},
                )
            )
            if "error-level/compression" not in families:
                families.append("error-level/compression")
        elif dcj.get("detected"):
            out.append(
                EvidenceDraft(
                    rule="forensics.double-compression.global",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim="The image was JPEG-compressed at least twice"
                    + (
                        f" (an earlier save at about quality {dcj.get('secondary_quality')})"
                        if dcj.get("secondary_quality") is not None
                        else ""
                    )
                    + ".",
                    source="double_compression",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail=dcj.get("observation"),
                    limitation="Re-saving is routine (messaging apps, editors, uploads). This is "
                    "compression history, not evidence of editing.",
                    refs=refs,
                    provider_version=dcj.get("version"),
                    data={
                        "secondary_quality": dcj.get("secondary_quality"),
                        "primary_quality": dcj.get("primary_quality"),
                        "periodic": dcj.get("periodic"),
                    },
                )
            )
        else:
            out.append(
                EvidenceDraft(
                    rule="forensics.double-compression.none",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="signal",
                    claim="No JPEG ghost of an earlier compression was found.",
                    source="double_compression",
                    detail=dcj.get("observation"),
                    limitation="An earlier save at a higher quality, resampling between saves or "
                    "flat content leaves no ghost. Absence says nothing.",
                    refs=refs,
                    provider_version=dcj.get("version"),
                )
            )

    # -- embedded thumbnail (independent family) -----------------------------------------------
    th_raw = method("thumbnail")
    th = applicable(th_raw)
    if th_raw and not th:
        out.append(
            EvidenceDraft(
                rule="forensics.thumbnail.na",
                category="forensics",
                level=EvidenceLevel.UNKNOWN,
                kind="unknown",
                claim="No embedded thumbnail is available to compare against.",
                source="thumbnail",
                detail=th_raw.get("reason"),
                limitation="Most sharing paths strip EXIF thumbnails; absence proves nothing.",
                refs=["step:thumbnail", "row:image_forensics"],
            )
        )
    elif th:
        refs = ["step:thumbnail", "row:image_forensics"]
        flagged_here = False
        if th.get("mismatch_global"):
            flagged_here = True
            out.append(
                EvidenceDraft(
                    rule="forensics.thumbnail.mismatch",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim="The embedded EXIF thumbnail does not depict the current image content.",
                    source="thumbnail",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail=f"Correlation {float(th.get('correlation') or 0):.2f} between the "
                    "thumbnail and the downscaled image.",
                    limitation="The picture may have been replaced or heavily edited after the "
                    "thumbnail was made, or the thumbnail may belong to another file; some "
                    "cameras frame thumbnails differently.",
                    refs=refs,
                    provider_version=th.get("version"),
                    data={"correlation": th.get("correlation"), "family": "thumbnail"},
                )
            )
        elif th.get("anomaly"):
            flagged_here = True
            regions = th.get("regions") or []
            r = regions[0] if regions else None
            out.append(
                EvidenceDraft(
                    rule="forensics.thumbnail.region",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim=f"{len(regions)} localised region(s) differ from the embedded thumbnail "
                    "while the rest of the image matches it.",
                    source="thumbnail",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail=(
                        f"Largest region at ({r['x']}, {r['y']}), {r['width']} x {r['height']} px; "
                        f"correlation outside the regions "
                        f"{float(th.get('correlation_outside_regions') or 0):.2f}."
                        if r
                        else None
                    ),
                    limitation="Consistent with a local edit made after the thumbnail was "
                    "generated; thumbnail processing (sharpening, tone curve) can also differ "
                    "locally. The comparison runs at thumbnail resolution.",
                    refs=refs,
                    provider_version=th.get("version"),
                    data={"regions": regions, "family": "thumbnail"},
                )
            )
        if th.get("orientation_mismatch") or th.get("aspect_mismatch"):
            flagged_here = True
            what = (
                f"flipped or rotated ({th.get('best_transform')})"
                if th.get("orientation_mismatch")
                else "cropped to a different aspect ratio"
            )
            out.append(
                EvidenceDraft(
                    rule="forensics.thumbnail.geometry",
                    category="forensics",
                    level=EvidenceLevel.POSSIBLE,
                    kind="signal",
                    claim=f"The image appears to have been {what} after its thumbnail was made.",
                    source="thumbnail",
                    confidence=_conf(EvidenceLevel.POSSIBLE, t),
                    detail=f"Aspect ratio image {th.get('aspect_ratio_image')} vs thumbnail "
                    f"{th.get('aspect_ratio_thumbnail')}; best transform "
                    f"{th.get('best_transform')}.",
                    limitation="Cropping and rotating are routine edits; some devices store "
                    "thumbnails with their own framing or orientation.",
                    refs=refs,
                    provider_version=th.get("version"),
                    data={
                        "aspect_mismatch": th.get("aspect_mismatch"),
                        "orientation_mismatch": th.get("orientation_mismatch"),
                        "best_transform": th.get("best_transform"),
                        "family": "thumbnail",
                    },
                )
            )
        if flagged_here:
            families.append("thumbnail")
        else:
            out.append(
                EvidenceDraft(
                    rule="forensics.thumbnail.consistent",
                    category="forensics",
                    level=EvidenceLevel.UNKNOWN,
                    kind="signal",
                    claim="The embedded thumbnail matches the current image.",
                    source="thumbnail",
                    detail=th.get("observation"),
                    limitation="Any full resave regenerates the thumbnail, so a match says nothing "
                    "about edits made before the last save.",
                    refs=refs,
                    provider_version=th.get("version"),
                )
            )

    # -- independence: several independent families -> STRONG ---------------------------------
    if len(families) >= t.forensic_families_for_strong:
        out.insert(
            0,
            EvidenceDraft(
                rule="forensics.multiple",
                category="forensics",
                level=EvidenceLevel.STRONG,
                kind="signal",
                claim=f"{len(families)} independent forensic methods flag anomalies "
                f"({', '.join(families)}).",
                source="forensics",
                confidence=_conf(EvidenceLevel.STRONG, t),
                detail="Independent heuristics agreeing raises the weight of the observation. "
                "Each remains a heuristic with the failure modes listed on its own record.",
                limitation="Repeated content, depth of field and detail-rich areas can trip more "
                "than one method on an unedited photo. Strong is not proof.",
                refs=["row:image_forensics"],
                data={"families": families, "required": t.forensic_families_for_strong},
            ),
        )
    return out


# A recorded time must precede another by at least this much before it counts as a
# contradiction; clock skew and rounding never should.
TIME_CONFLICT_TOLERANCE_SECONDS = 60


def _conflict(
    rule: str, claim: str, a: EvidenceDraft, b: EvidenceDraft, *, detail: str, limitation: str
) -> EvidenceDraft:
    return EvidenceDraft(
        rule=rule,
        category="synthesis",
        level=EvidenceLevel.UNKNOWN,
        kind="conflict",
        claim=claim,
        source="evidence-engine",
        confidence=None,
        detail=detail,
        limitation=limitation,
        refs=[*a.refs, *b.refs],
        conflicts_with=[a.rule, b.rule],
    )


def _conflict_rules(
    drafts: list[EvidenceDraft], o: Observations | None = None
) -> list[EvidenceDraft]:
    """docs/07: keep both sides, surface the conflict, lower synthesis confidence.

    Rules: a validated manifest against a STRONG/PROBABLE contrary signal; a recorded
    capture time *after* the manifest's signing time; a source published *before* the
    recorded capture time. Naive timestamps are compared as if UTC with a tolerance,
    and the limitation says so.
    """
    by_rule = {d.rule: d for d in drafts}
    out: list[EvidenceDraft] = []
    verified_prov = by_rule.get("provenance.valid")
    captured = by_rule.get("metadata.captured")
    captured_dt, captured_tz = (
        parse_timestamp((captured.data.get("captured_at") or {}).get("parsed"))
        if captured
        else (None, False)
    )
    tol = TIME_CONFLICT_TOLERANCE_SECONDS

    if verified_prov and captured and captured_dt is not None:
        signed_dt, _ = parse_timestamp(verified_prov.data.get("signed_at"))
        if signed_dt is not None:
            gap = (as_utc(captured_dt) - as_utc(signed_dt)).total_seconds()
            if gap > tol:
                out.append(
                    _conflict(
                        "conflict.capture-after-signing",
                        "Evidence conflicts: the metadata capture time is later than the "
                        "C2PA signing time.",
                        verified_prov,
                        captured,
                        detail=f"Captured {captured_dt.isoformat()} versus signed "
                        f"{signed_dt.isoformat()} ({gap / 3600:.1f} h later).",
                        limitation="A camera clock set wrong, an edited EXIF field or a "
                        "missing timezone"
                        + ("" if captured_tz else " (the capture time has none)")
                        + " can all produce this; neither record is discarded.",
                    )
                )

    sources = by_rule.get("sources.matches")
    if sources and captured and captured_dt is not None and o is not None:
        earliest: datetime | None = None
        for m in o.search_matches:
            dt, _ = parse_timestamp(getattr(m, "published_at", None))
            if dt is not None and (earliest is None or as_utc(dt) < as_utc(earliest)):
                earliest = dt
        if earliest is not None:
            gap = (as_utc(captured_dt) - as_utc(earliest)).total_seconds()
            if gap > tol:
                out.append(
                    _conflict(
                        "conflict.published-before-capture",
                        "Evidence conflicts: a source reports this content published before "
                        "the recorded capture time.",
                        sources,
                        captured,
                        detail=f"Earliest reported publication {earliest.isoformat()} versus "
                        f"capture {captured_dt.isoformat()} ({gap / 86400:.1f} days earlier).",
                        limitation="Provider dates are as reported by the source and may be "
                        "wrong; the match may be a look-alike; the capture time can be wrong "
                        "or lack a timezone. Both records are retained.",
                    )
                )
    signed_type = by_rule.get("provenance.source-type")
    declared_type = by_rule.get("metadata.source-type")
    if (
        signed_type
        and declared_type
        and bool(signed_type.data.get("algorithmic")) != bool(declared_type.data.get("algorithmic"))
    ):
        out.append(
            _conflict(
                "conflict.source-type",
                "Evidence conflicts: the signed C2PA source type and the metadata source type "
                "disagree on algorithmic origin.",
                signed_type,
                declared_type,
                detail=f'Signed "{signed_type.data.get("digital_source_type")}" versus metadata '
                f'"{declared_type.data.get("digital_source_type")}".',
                limitation="Metadata fields can be edited freely after signing; the signed value "
                "is the one the signer vouched for. Both records are retained.",
            )
        )
    prov_row = o.provenance if o is not None else None
    chain_conflict = bool(
        (getattr(prov_row, "normalized_json", None) or {}).get("manifest_order_conflict")
    )
    head = verified_prov or by_rule.get("provenance.invalid")
    if chain_conflict and head is not None:
        out.append(
            EvidenceDraft(
                rule="conflict.manifest-order",
                category="synthesis",
                level=EvidenceLevel.UNKNOWN,
                kind="conflict",
                claim="Evidence conflicts: a manifest in the chain was signed before one of the "
                "ingredients it claims to derive from.",
                source="evidence-engine",
                confidence=None,
                detail="Signing times of the manifest chain are out of order.",
                limitation="Signing clocks may be wrong or unsynchronised; the order is compared "
                "with a tolerance. Both manifests are retained.",
                refs=list(head.refs),
                conflicts_with=[head.rule],
            )
        )
    if verified_prov:
        opposing = [
            d
            for d in drafts
            if d.rule in {"forensics.multiple", "ai.signal"}
            and d.level in {EvidenceLevel.STRONG, EvidenceLevel.PROBABLE}
        ]
        for d in opposing:
            out.append(
                EvidenceDraft(
                    rule=f"conflict.provenance-vs-{d.category}",
                    category="synthesis",
                    level=EvidenceLevel.UNKNOWN,
                    kind="conflict",
                    claim="Evidence conflicts: an intact, validated C2PA manifest coexists with "
                    f"a {d.level} {d.category} signal.",
                    source="evidence-engine",
                    confidence=None,
                    detail=f'"{verified_prov.claim}" versus "{d.claim}"',
                    limitation="Both records are retained. A valid manifest covers what its "
                    "signer asserted, not everything about the picture; the signal may also be "
                    "a false positive. Synthesis confidence is lowered accordingly.",
                    refs=[*verified_prov.refs, *d.refs],
                    conflicts_with=[verified_prov.rule, d.rule],
                )
            )
    return out


def build_evidence(o: Observations, t: EvidenceThresholds) -> list[EvidenceDraft]:
    """All evidence for one analysis, in report order; deterministic for the same inputs."""
    drafts: list[EvidenceDraft] = []
    drafts += _file_rules(o, t)
    if o.analysis_type == "image":
        drafts += _provenance_rules(o, t)
        drafts += _metadata_rules(o, t)
        drafts += _image_match_rules(o, t)
        drafts += _forensic_rules(o, t)
    else:
        drafts += _text_rules(o, t)
        drafts += _text_match_rules(o, t)
    drafts += _ai_rules(o, t)
    drafts += _source_rules(o, t)
    drafts = apply_overrides(drafts, t)
    drafts += _conflict_rules(drafts, o)
    return drafts


def summarise(drafts: Sequence[EvidenceDraft]) -> dict[str, int]:
    counts = {level.value: 0 for level in EvidenceLevel}
    for d in drafts:
        counts[str(d.level)] += 1
    return counts
