"""Deterministic text processing: normalization, statistics, fingerprints."""

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
    "TextStatistics",
    "TextStructure",
    "compute_statistics",
    "compute_structure",
    "detect_language",
    "normalize_text",
]
