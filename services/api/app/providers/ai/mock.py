"""Mock detector for development and tests. Deterministic, clearly labelled, never calibrated.

The score is derived from the content hash so identical inputs always produce
identical results (which also exercises the caching path realistically).
"""

import hashlib
from typing import Any

from app.providers.ai.base import (
    GENERIC_LIMITATIONS,
    DetectionResult,
    Modality,
    label_for_score,
)

MOCK_MODEL = "mock-detector"
MOCK_VERSION = "0.0"


class MockAIDetector:
    name = "mock"
    modalities = frozenset({"image", "text"})

    def __init__(self, *, high: float, medium: float, fixed_score: float | None = None) -> None:
        self._high = high
        self._medium = medium
        self._fixed = fixed_score

    async def detect(
        self, content: bytes | str, *, modality: Modality, metadata: dict[str, Any]
    ) -> DetectionResult:
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        if self._fixed is not None:
            score = self._fixed
        else:
            digest = hashlib.sha256(b"verixa-mock:" + data).digest()
            score = round(int.from_bytes(digest[:4], "big") / 0xFFFFFFFF, 4)
        return DetectionResult(
            provider=self.name,
            model=MOCK_MODEL,
            model_version=MOCK_VERSION,
            modality=modality,
            score=score,
            label=label_for_score(score, high=self._high, medium=self._medium),
            calibrated=False,
            raw={"mock": True, "derived_from": "sha256(content)", "bytes": len(data)},
            latency_ms=0,
            estimated_cost=0.0,
            limitations=[
                "This is a MOCK detector: the score is derived from the content hash and "
                "carries no information about AI generation.",
                *GENERIC_LIMITATIONS,
            ],
        )
