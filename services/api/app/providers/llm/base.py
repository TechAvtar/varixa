"""LLM synthesis interface.

The model is an *explanation layer only* (docs/07 §LLM rules). It receives structured
evidence and must return prose that answers the six summary-template questions, each
grounded in evidence ids. Nothing here may create evidence, change a level, invent a
timestamp or a previous version, or claim certainty the evidence does not carry; the
service layer verifies the output against those rules before it is shown.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

PROMPT_VERSION = "v1"

# The six questions of the docs/07 summary template, in order. Keys are stable API names.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("verified", "What is directly verified?"),
    ("signals", "What technical signals were found?"),
    ("probabilistic", "What signals are probabilistic?"),
    ("conflicts", "What evidence conflicts?"),
    ("unknown", "What remains unknown?"),
    ("improve", "What additional evidence would improve confidence?"),
)
SECTION_KEYS = tuple(k for k, _ in SECTIONS)


class LLMSynthesisError(Exception):
    """The provider was called but failed (network, auth, 5xx, unparseable payload)."""


class LLMSynthesisUnavailableError(LLMSynthesisError):
    """The provider cannot serve requests at all (not configured, missing credentials)."""


@dataclass(frozen=True)
class EvidenceForModel:
    """The only thing the model learns about a record. Never raw content, never keys/URLs."""

    id: str
    rule: str
    category: str
    level: str
    kind: str
    claim: str
    source: str
    confidence: float | None
    limitation: str | None
    conflicts_with: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule": self.rule,
            "category": self.category,
            "level": self.level,
            "kind": self.kind,
            "claim": self.claim,
            "source": self.source,
            "confidence": self.confidence,
            "limitation": self.limitation,
            "conflicts_with": list(self.conflicts_with),
        }


@dataclass(frozen=True)
class TimelineForModel:
    event_type: str
    event_time: str | None
    certainty: str
    description: str

    def to_json(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "event_time": self.event_time,
            "certainty": self.certainty,
            "description": self.description,
        }


@dataclass(frozen=True)
class SynthesisRequest:
    """Structured evidence only. ``fingerprint`` identifies the exact evidence set sent."""

    analysis_type: str
    evidence: list[EvidenceForModel]
    timeline: list[TimelineForModel]
    counts: dict[str, int]
    conflicts: int
    synthesis_confidence: float
    fingerprint: str
    prompt_version: str = PROMPT_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "analysis_type": self.analysis_type,
            "evidence": [e.to_json() for e in self.evidence],
            "timeline": [t.to_json() for t in self.timeline],
            "counts": dict(self.counts),
            "conflicts": self.conflicts,
            "synthesis_confidence": self.synthesis_confidence,
            "prompt_version": self.prompt_version,
        }


@dataclass(frozen=True)
class SectionDraft:
    text: str
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SynthesisResult:
    provider: str
    model: str
    model_version: str
    sections: dict[str, SectionDraft]  # keyed by SECTION_KEYS
    raw: dict[str, Any] = field(default_factory=dict)
    latency_ms: int | None = None
    request_id: str | None = None
    cached: bool = False
    estimated_cost: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


class LLMSynthesizer(Protocol):
    name: str

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult: ...


def sections_to_json(sections: dict[str, SectionDraft]) -> dict[str, Any]:
    return {k: {"text": s.text, "evidence_ids": list(s.evidence_ids)} for k, s in sections.items()}


def sections_from_json(data: dict[str, Any]) -> dict[str, SectionDraft]:
    out: dict[str, SectionDraft] = {}
    for key in SECTION_KEYS:
        raw = data.get(key) or {}
        if isinstance(raw, str):
            out[key] = SectionDraft(text=raw)
        else:
            out[key] = SectionDraft(
                text=str(raw.get("text") or ""),
                evidence_ids=[str(x) for x in (raw.get("evidence_ids") or [])],
            )
    return out
