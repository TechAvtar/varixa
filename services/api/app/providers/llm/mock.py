"""Deterministic synthesiser for development and tests: template prose over the evidence.

It never adds a fact the evidence does not carry: every sentence is assembled from
record claims and every section cites the ids it used, which is exactly what the
grounding validator later demands of a real model.
"""

from typing import Any

from app.providers.llm.base import (
    PROMPT_VERSION,
    SectionDraft,
    SynthesisRequest,
    SynthesisResult,
)

MOCK_MODEL = "mock-synthesiser"
MOCK_VERSION = "0.0"


def _join(claims: list[str]) -> str:
    return " ".join(c if c.endswith(".") else c + "." for c in claims)


class MockLLMSynthesizer:
    name = "mock"

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        ev = request.evidence
        verified = [e for e in ev if e.level == "VERIFIED" and e.kind == "fact"]
        signals = [e for e in ev if e.kind == "signal" and e.level in {"STRONG", "POSSIBLE"}]
        probabilistic = [
            e for e in ev if e.kind == "signal" and (e.category == "ai" or e.level == "PROBABLE")
        ]
        conflicts = [e for e in ev if e.kind == "conflict"]
        unknown = [e for e in ev if e.level == "UNKNOWN" and e.kind != "conflict"]

        def section(items: list[Any], empty: str) -> SectionDraft:
            if not items:
                return SectionDraft(text=empty, evidence_ids=[])
            return SectionDraft(
                text=_join([i.claim for i in items]), evidence_ids=[i.id for i in items]
            )

        improve_bits: list[str] = []
        if any(e.rule == "provenance.absent" for e in ev):
            improve_bits.append("an original with intact content credentials")
        if any(e.rule in {"ai.unavailable", "sources.unavailable"} for e in ev):
            improve_bits.append("a configured AI detector or source-search provider")
        if any(e.rule == "metadata.none" for e in ev):
            improve_bits.append("the camera original with metadata preserved")
        if not improve_bits:
            improve_bits.append("independent copies of the content with their own history")
        sections = {
            "verified": section(verified, "Nothing is directly verified beyond the stored bytes."),
            "signals": section(signals, "No technical signals were recorded."),
            "probabilistic": section(
                probabilistic, "No probabilistic signal (detector or model score) was evaluated."
            ),
            "conflicts": section(conflicts, "No conflicting evidence was found."),
            "unknown": section(unknown, "Nothing was left unknown."),
            "improve": SectionDraft(
                text="Confidence would improve with " + " and ".join(improve_bits) + ".",
                evidence_ids=[e.id for e in ev if e.level == "UNKNOWN"][:3],
            ),
        }
        return SynthesisResult(
            provider=self.name,
            model=MOCK_MODEL,
            model_version=MOCK_VERSION,
            sections=sections,
            raw={"prompt_version": PROMPT_VERSION, "records": len(ev)},
            latency_ms=0,
            estimated_cost=0.0,
            tokens_in=0,
            tokens_out=0,
        )
