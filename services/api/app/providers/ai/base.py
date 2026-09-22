"""AI-generation detector interface.

A detector returns a *probabilistic signal*. Nothing in this package (or in any
adapter) may present its output as proof of authorship. Every result carries
provider/model/version so it can be audited and re-evaluated when models change.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Modality = Literal["image", "text"]
Label = Literal["likely_ai", "uncertain", "likely_human", "unavailable"]


class AIDetectorError(Exception):
    """The provider was called but failed (network, auth, 5xx, bad payload)."""


class AIDetectorUnavailableError(AIDetectorError):
    """The provider cannot serve this request at all (not configured, unsupported modality)."""


@dataclass(frozen=True)
class DetectionResult:
    provider: str
    model: str
    model_version: str
    modality: Modality
    # 0.0 = no AI signal ... 1.0 = strongest AI signal, as reported by the provider.
    # None when the provider gave no score. Not calibrated across providers.
    score: float | None
    label: Label
    calibrated: bool
    raw: dict[str, Any] = field(default_factory=dict)
    latency_ms: int | None = None
    request_id: str | None = None
    cached: bool = False
    # Estimated provider cost in USD for this call (None when unknown). Cached hits cost 0.
    estimated_cost: float | None = None
    limitations: list[str] = field(default_factory=list)


class AIDetector(Protocol):
    name: str
    modalities: frozenset[str]

    async def detect(
        self, content: bytes | str, *, modality: Modality, metadata: dict[str, Any]
    ) -> DetectionResult: ...


def label_for_score(score: float | None, *, high: float, medium: float) -> Label:
    """Map a provider score to a coarse label using configurable thresholds."""
    if score is None:
        return "unavailable"
    if score >= high:
        return "likely_ai"
    if score >= medium:
        return "uncertain"
    return "likely_human"


GENERIC_LIMITATIONS = [
    "Detector scores are statistical estimates and are known to produce false positives "
    "and false negatives, especially on short, edited, translated or compressed content.",
    "A score is not evidence of who created the content; it is one signal to weigh with "
    "provenance, metadata and source evidence.",
]
