"""Deterministic text processing: normalization, statistics, fingerprints."""

from app.services.text.fingerprints import (
    TextFingerprints,
    canonical_form,
    compute_text_fingerprints,
    estimate_jaccard,
)
from app.services.text.language import LanguageGuess, detect_language
from app.services.text.normalize import NormalizationReport, NormalizedText, normalize_text
from app.services.text.statistics import (
    TextStatistics,
    TextStructure,
    compute_statistics,
    compute_structure,
)

__all__ = [
    "LanguageGuess",
    "NormalizationReport",
    "NormalizedText",
    "TextFingerprints",
    "TextStatistics",
    "TextStructure",
    "canonical_form",
    "compute_statistics",
    "compute_structure",
    "compute_text_fingerprints",
    "detect_language",
    "estimate_jaccard",
    "normalize_text",
]
